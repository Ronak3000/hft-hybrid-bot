import os
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

# 1. Point Python directly to your C++ build folder
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
build_path = project_root / "backend_cpp" / "build"

for path in (project_root, build_path):
    sys.path.insert(0, str(path))

from engine.rl_trading.envs.trading_env import TradingEnv
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

def main():
    print("--- Booting Historical Evaluation Environment ---")
    
    # 1. Instantiate the raw environment
    raw_env = TradingEnv()
    
    # 2. Wrap in a single chronological process for proper equity curve plotting
    env = DummyVecEnv([lambda: raw_env])
    
    # 3. Load saved training normalization statistics
    stats_path = os.path.join("models", "vec_normalize_v2.pkl")
    if os.path.exists(stats_path):
        print(f"Loading running normalization stats from {stats_path}...")
        env = VecNormalize.load(stats_path, env)
        env.training = False       # Lock running mean/std averages
        env.norm_reward = False    # Keep raw dollar values for plotting
    else:
        print(f"CRITICAL WARNING: No normalization statistics found at {stats_path}. Run train.py first!")
        return

    # 4. Load the trained brain
    model_path = os.path.join("models", "ppo_hft_v2.zip")
    if not os.path.exists(model_path):
        print(f"CRITICAL: Could not find model at {model_path}. Run train.py first.")
        return

    print("Loading trained PPO weights...")
    model = PPO.load(model_path, env=env)
    
    # Reset the normalized environment
    obs = env.reset()
    
    # Tracking arrays for plotting
    net_worth_history = []
    price_history = []
    inventory_history = []  # New: Track physical BTC holdings
    
    print("Simulating full historical trading day. This will run fast...")
    
    steps = 0
    while True:
        # Deterministic inference: no random exploration during evaluation
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, done, infos = env.step(action)
        
        info = infos[0]
        net_worth_history.append(info["net_worth"])
        
        # Pull direct market prices and inventory from the unwrapped environment
        best_bid = getattr(raw_env, 'best_bid', 0)
        best_ask = getattr(raw_env, 'best_ask', 0)
        
        if best_bid > 0 and best_ask > 0:
            mid_price = (best_bid + best_ask) / 2.0
        else:
            mid_price = getattr(raw_env, 'fair_price', 62500.0)
            
        price_history.append(mid_price)
        
        # Extract physical BTC inventory directly from the underlying environment
        inventory_history.append(getattr(raw_env, 'inventory_btc', 0.0))
        
        steps += 1
        
        if done[0]:
            if info.get("net_worth", 1000000) < 100000:
                print(f"Agent went bankrupt at step {steps}!")
            else:
                print(f"Reached end of historical CSV data at step {steps}.")
            break
            
    print(f"Evaluation complete. Final Net Worth: ${net_worth_history[-1]:.2f}")
    
    # --- 3-Panel Institutional Plotting ---
    print("Generating PnL, Price, and Inventory telemetry charts...")
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    
    # Top Chart: AI Net Worth
    ax1.plot(net_worth_history, color='blue', linewidth=2, label="AI Portfolio Value")
    ax1.axhline(y=1000000, color='red', linestyle='--', alpha=0.5, label="Starting Balance ($1M)")
    ax1.set_title("HFT AI: Real Historical LOB Backtest", fontsize=14, fontweight='bold')
    ax1.set_ylabel("Net Worth ($)", fontsize=11)
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)
    
    # Middle Chart: Market Price
    ax2.plot(price_history, color='gray', linewidth=1, alpha=0.7, label="Asset Mid-Price")
    ax2.set_ylabel("Price ($)", fontsize=11)
    ax2.legend(loc="upper left")
    ax2.grid(True, alpha=0.3)
    
    # Bottom Chart: Physical BTC Inventory Exposure
    ax3.plot(inventory_history, color='purple', linewidth=1.5, label="Physical Inventory Exposure (BTC)")
    ax3.axhline(y=0, color='black', linestyle='-', alpha=0.4)
    ax3.axhline(y=6.0, color='red', linestyle=':', alpha=0.6, label="Max Long Limit (+6 BTC)")
    ax3.axhline(y=-6.0, color='red', linestyle=':', alpha=0.6, label="Max Short Limit (-6 BTC)")
    ax3.set_xlabel("Historical Event (Timestep)", fontsize=11)
    ax3.set_ylabel("Inventory (BTC)", fontsize=11)
    ax3.legend(loc="upper left")
    ax3.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig("evaluation_plot_historical.png")
    plt.show()

if __name__ == "__main__":
    main()