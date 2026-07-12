import sys
import os
import gymnasium as gym
from gymnasium import spaces
import numpy as np

# Inject C++ binary path
build_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend_cpp/build'))
if build_path not in sys.path:
    sys.path.append(build_path)

import hft_engine

class TradingEnv(gym.Env):
    """
    Institutional-Grade Hybrid RL + Mathematical Market Making Environment.
    Features bare-metal C++ matching, O(1) circular volatility buffers, 
    price-invariant scaling, order persistence deadbands, hard inventory boundaries,
    and native quote suppression (Leave/Enter Market).
    """
    def __init__(self, symbol="BTC/USDT", start_date=None, end_date=None,
                 starting_cash=1000000.0, base_trade_size=0.5, 
                 max_inventory=10.0, maker_fee=-0.0001, 
                 penalty_factor=0.1, kappa=1.5, live_mode=False):
        super(TradingEnv, self).__init__()
        
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.live_mode = live_mode
        self.is_quoting = True  # Native quote suppressor flag
        
        # Action Space: [Gamma Modifier, Spread Multiplier]
        self.action_space = spaces.Box(
            low=np.array([0.05, 0.5], dtype=np.float32), 
            high=np.array([0.5, 10.0], dtype=np.float32), 
            dtype=np.float32
        )
        
        # Observation Space: Explicit float32 wrapping to prevent Gymnasium downcasting warnings
        self.observation_space = spaces.Box(
            low=np.float32(-np.inf), high=np.float32(np.inf), shape=(4,), dtype=np.float32
        )
        
        self.engine = hft_engine.OrderBook() 
        
        if not self.live_mode:
            clean_symbol = symbol.replace("/", "").replace("-", "")
            data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), f"../../../data/{clean_symbol}.csv"))
            if not os.path.exists(data_path):
                data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data/test_data.csv"))
            self.engine.load_history_csv(data_path)
        
        self.STARTING_CASH = starting_cash
        self.BASE_TRADE_SIZE = float(base_trade_size)      
        self.MAX_INVENTORY = float(max_inventory)        
        self.KAPPA = float(kappa)                
        self.PENALTY_FACTOR = penalty_factor       
        self.MAKER_FEE = maker_fee        
        
        self.window_size = 100
        self.price_buffer = np.zeros(self.window_size, dtype=np.float32)
        self.buffer_idx = 0
        self.buffer_filled = False
        
        self.reset()

    def inject_live_tick(self, price: float, volume: float, is_buyer_maker: bool):
        self.live_price = float(price)
        scaled_price = int(round(self.live_price))
        scaled_volume = int(round(volume * 10000)) if volume < 1.0 else int(volume)
        self.engine.inject_live_tick(scaled_price, scaled_volume, is_buyer_maker)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        self.cash = self.STARTING_CASH
        self.inventory_btc = 0.0  
        self.inventory_lots = 0   
        self.prev_net_worth = self.STARTING_CASH
        self.mid_price = 62500.0
        self.volatility = 0.1
        self.resting_bid = 0.0
        self.resting_ask = 0.0
        self.last_anchor_price = 62500.0
        self.is_quoting = True
        
        self.price_buffer.fill(0.0)
        self.buffer_idx = 0
        self.buffer_filled = False
        
        if self.live_mode:
            self.mid_price = getattr(self, 'live_price', 62500.0)
            self.last_anchor_price = self.mid_price
        else:
            self.engine.reset_cache()
            price, _ = self.engine.advance_tick()
            self.mid_price = price
            self.last_anchor_price = price
        
        return self._get_observation(), {}

    def _get_observation(self):
        self.price_buffer[self.buffer_idx] = self.mid_price
        self.buffer_idx = (self.buffer_idx + 1) % self.window_size
        if self.buffer_idx == 0:
            self.buffer_filled = True
            
        valid_prices = self.price_buffer if self.buffer_filled else self.price_buffer[:self.buffer_idx+1]
        if len(valid_prices) > 2:
            self.volatility = max(float(np.std(valid_prices)), 0.1)
        else:
            self.volatility = 0.1
            
        obi = float(self.engine.get_obi())
        return np.array([self.mid_price, self.inventory_btc, self.volatility, obi], dtype=np.float32)

    def step(self, action):
        # 1. Always advance clock first so market price stays 100% synchronized!
        if self.live_mode:
            market_trade_price = self.live_price
            is_out_of_data = False
        else:
            market_trade_price, is_out_of_data = self.engine.advance_tick()
            
        self.mid_price = market_trade_price 
        triggered_side = None

        # --- 2. NATIVE QUOTE SUPPRESSOR ---
        # If quoting is paused ("Leave Market"), completely bypass quote calculation and trade matching!
        if not getattr(self, 'is_quoting', True):
            self.resting_bid = 0.0
            self.resting_ask = 0.0
            self.best_bid = 0.0
            self.best_ask = 0.0
            self.fair_price = self.mid_price
        else:
            # --- Active Quoting Mode ---
            gamma_modifier, spread_multiplier = action

            # Price-Invariant Gamma Scaling
            price_scale = 60000.0 / max(self.mid_price, 1.0)
            scaled_gamma = float(gamma_modifier * price_scale)

            quotes = self.engine.get_as_quotes(
                self.mid_price, float(self.inventory_btc), self.volatility, 
                scaled_gamma, self.KAPPA, float(spread_multiplier)
            )

            # HFT Top-of-Book Clamp (0.3 bps to 10 bps depth)
            min_offset = self.mid_price * 0.00003  
            max_offset = self.mid_price * 0.0001   
            
            raw_half_spread = (quotes.ask_price - quotes.bid_price) / 2.0
            clamped_half_spread = np.clip(raw_half_spread, min_offset, max_offset)

            target_bid = self.mid_price - clamped_half_spread
            target_ask = self.mid_price + clamped_half_spread

            # Order Persistence Deadband (3 basis points stationary anchor)
            if not hasattr(self, 'resting_bid') or self.resting_bid == 0.0:
                self.resting_bid = target_bid
                self.resting_ask = target_ask
                self.last_anchor_price = self.mid_price

            price_drift = abs(self.mid_price - getattr(self, 'last_anchor_price', self.mid_price)) / max(self.mid_price, 1.0)
            if price_drift > 0.0003 or not self.live_mode:  
                self.resting_bid = target_bid
                self.resting_ask = target_ask
                self.last_anchor_price = self.mid_price

            bid_price = self.resting_bid
            ask_price = self.resting_ask
            self.best_bid = bid_price
            self.best_ask = ask_price
            self.fair_price = self.mid_price

            # --- 3. TRUE TRAINED TRADE SIZING ---
            # Scale the model's exact trained base_trade_size by current market volatility
            target_vol = max(self.mid_price * 0.005, 0.01)
            vol_scalar = np.clip(target_vol / max(self.volatility, 0.01), 0.2, 1.0)
            current_trade_size = float(self.BASE_TRADE_SIZE * vol_scalar)

            # Microstructural Trade-Through Simulation with Hard Boundary Enforcement
            if market_trade_price <= bid_price and (self.inventory_btc + current_trade_size) <= self.MAX_INVENTORY:
                self.inventory_lots += 1
                self.inventory_btc += current_trade_size
                trade_value = bid_price * current_trade_size
                fee_paid = trade_value * self.MAKER_FEE
                self.cash -= (trade_value + fee_paid)
                triggered_side = "BUY"
                self.resting_bid = 0.0  # Reset anchor immediately upon execution

            elif market_trade_price >= ask_price and (self.inventory_btc - current_trade_size) >= -self.MAX_INVENTORY:
                self.inventory_lots -= 1
                self.inventory_btc -= current_trade_size
                trade_value = ask_price * current_trade_size
                fee_paid = trade_value * self.MAKER_FEE
                self.cash += (trade_value - fee_paid)
                triggered_side = "SELL"
                self.resting_bid = 0.0  # Reset anchor immediately upon execution

        # 4. Valuation & Rewards
        current_net_worth = self.cash + (self.inventory_btc * market_trade_price)
        step_pnl = current_net_worth - self.prev_net_worth
        self.prev_net_worth = current_net_worth

        inventory_penalty = self.PENALTY_FACTOR * (self.inventory_btc ** 2)
        reward = step_pnl - inventory_penalty
        
        terminated = False
        if current_net_worth < self.STARTING_CASH * 0.8:  
            terminated = True
            reward -= 100000 
            
        info = {
            "net_worth": current_net_worth,
            "inventory": self.inventory_btc,
            "latest_executions": []
        }
        
        if triggered_side and self.live_mode:
            info["latest_executions"].append({
                "side": triggered_side,
                "price": round(bid_price if triggered_side == "BUY" else ask_price, 2),
                "size": round(current_trade_size, 4),
                "realized_pnl": round(step_pnl, 2) if triggered_side == "SELL" else 0.0
            })
        
        return self._get_observation(), float(reward), terminated, is_out_of_data, info