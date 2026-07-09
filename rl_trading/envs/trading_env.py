import gymnasium as gym
from gymnasium import spaces
import numpy as np
import hft_engine

class TradingEnv(gym.Env):
    """
    Institutional-Grade Hybrid RL + Mathematical Market Making Environment.
    Features bare-metal C++ matching, O(1) circular volatility buffers, 
    dynamic flow-adjusted lot sizing, and hard inventory circuit breakers.
    """
    def __init__(self, data_path="test_data.csv"):
        super(TradingEnv, self).__init__()
        
        # Action Space: [Gamma Modifier, Spread Multiplier]
        # Spread multiplier up to 10.0 gives the AI a massive shield during real flash crashes
        self.action_space = spaces.Box(
            low=np.array([0.05, 0.5]), 
            high=np.array([0.5, 10.0]), 
            dtype=np.float32
        )
        
        # Observation Space: [mid_price, inventory_btc, rolling_volatility, obi]
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(4,), dtype=np.float32
        )
        
        self.engine = hft_engine.OrderBook() 
        self.engine.load_history_csv(data_path)
        
        self.STARTING_CASH = 1000000.0
        self.BASE_TRADE_SIZE = 0.5      
        self.MAX_INVENTORY = 6.0        
        self.KAPPA = 1.5                
        self.PENALTY_FACTOR = 0.1       # Lowered to let pure Dollar PnL drive behavior 
        self.MAKER_FEE = -0.0001        
        
        self.window_size = 100
        self.price_buffer = np.zeros(self.window_size, dtype=np.float32)
        self.buffer_idx = 0
        self.buffer_filled = False
        
        self.reset()

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        self.cash = self.STARTING_CASH
        self.inventory_btc = 0.0  
        self.inventory_lots = 0   
        self.prev_net_worth = self.STARTING_CASH
        self.mid_price = 62500.0
        self.volatility = 0.1
        
        self.price_buffer.fill(0.0)
        self.buffer_idx = 0
        self.buffer_filled = False
        
        self.engine.reset_cache()
        price, _ = self.engine.advance_tick()
        self.mid_price = price
        
        return self._get_observation(), {}

    def _get_observation(self):
        self.price_buffer[self.buffer_idx] = self.mid_price
        self.buffer_idx = (self.buffer_idx + 1) % self.window_size
        if self.buffer_idx == 0:
            self.buffer_filled = True
            
        # Fast ABSOLUTE DOLLAR VOLATILITY computation
        valid_prices = self.price_buffer if self.buffer_filled else self.price_buffer[:self.buffer_idx+1]
        if len(valid_prices) > 2:
            self.volatility = max(float(np.std(valid_prices)), 0.1)
        else:
            self.volatility = 0.1
            
        obi = float(self.engine.get_obi())
        return np.array([self.mid_price, self.inventory_btc, self.volatility, obi], dtype=np.float32)

    def step(self, action):
        gamma_modifier, spread_multiplier = action

        # 1. Ask C++ to compute Optimal Stochastic Spread using raw physical BTC
        quotes = self.engine.get_as_quotes(
            self.mid_price, 
            float(self.inventory_btc), 
            self.volatility, 
            gamma_modifier, 
            self.KAPPA, 
            spread_multiplier
        )

        # --- THE PASSIVE MAKER CLAMP ---
        # Prevent variance explosions from making the AI cross the spread and pay market taker fees
        bid_price = min(quotes.bid_price, self.mid_price - 0.5)
        ask_price = max(quotes.ask_price, self.mid_price + 0.5)
        
        self.best_bid = bid_price
        self.best_ask = ask_price
        self.fair_price = self.mid_price

        # Dynamic Volatility Sizing (Target ~ $300 vol)
        target_vol = 300.0
        vol_scalar = np.clip(target_vol / max(self.volatility, 0.1), 0.2, 1.0)
        current_trade_size_btc = float(self.BASE_TRADE_SIZE * vol_scalar)

        # 2. Advance C++ Clock
        market_trade_price, is_out_of_data = self.engine.advance_tick()
        self.mid_price = market_trade_price 
        
        # 3. Simulate Trade-Through
        if market_trade_price <= bid_price and self.inventory_btc < self.MAX_INVENTORY:
            self.inventory_lots += 1
            self.inventory_btc += current_trade_size_btc
            trade_value = bid_price * current_trade_size_btc
            fee_paid = trade_value * self.MAKER_FEE
            self.cash -= (trade_value + fee_paid)

        elif market_trade_price >= ask_price and self.inventory_btc > -self.MAX_INVENTORY:
            self.inventory_lots -= 1
            self.inventory_btc -= current_trade_size_btc
            trade_value = ask_price * current_trade_size_btc
            fee_paid = trade_value * self.MAKER_FEE
            self.cash += (trade_value - fee_paid)

        # 4. Exact Physical Valuation
        current_net_worth = self.cash + (self.inventory_btc * market_trade_price)
        step_pnl = current_net_worth - self.prev_net_worth
        self.prev_net_worth = current_net_worth

        # 5. Quadratic Penalty
        inventory_penalty = self.PENALTY_FACTOR * (self.inventory_btc ** 2)
        reward = step_pnl - inventory_penalty
        
        terminated = False
        if current_net_worth < self.STARTING_CASH * 0.8:  
            terminated = True
            reward -= 100000 
            
        info = {"net_worth": current_net_worth}
        
        return self._get_observation(), float(reward), terminated, is_out_of_data, info