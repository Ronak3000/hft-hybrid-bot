import sys
import os
import multiprocessing
from pathlib import Path

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
build_path = project_root / "backend_cpp" / "build"

for path in (project_root, build_path):
    sys.path.insert(0, str(path))

from engine.rl_trading.envs.trading_env import TradingEnv
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv, VecNormalize

def make_env():
    """Helper function to instantiate isolated environment processes."""
    def _init():
        return TradingEnv()
    return _init

def main():
    # Detect available CPU cores (cap at 8 to prevent RAM saturation)
    num_cpu = min(multiprocessing.cpu_count(), 8)
    print(f"Spawning {num_cpu} parallel C++ market environments across CPU cores...")
    
    # Use SubprocVecEnv for true multi-core parallel execution
    env = SubprocVecEnv([make_env() for _ in range(num_cpu)])
    env = VecNormalize(env, norm_obs=True, norm_reward=True, clip_obs=10.0)
    
    print("Generating high-throughput PPO brain...")
    model = PPO(
        "MlpPolicy", 
        env, 
        verbose=1, 
        learning_rate=0.0003, 
        n_steps=1024,   # 1024 steps * 8 cores = 8,192 steps per rollout buffer
        batch_size=512, # Large batch size utilizes vector SIMD instructions heavily
        n_epochs=5,     # Cut epoch loops in half for rapid iteration
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.005, 
        vf_coef=0.5,
        tensorboard_log="./tensorboard_logs/"
    )
    
    print("Commencing Multi-Core Training Loop (2,000,000 steps)...")
    model.learn(total_timesteps=2000000)
    
    os.makedirs("models", exist_ok=True)
    save_path = os.path.join("models", "ppo_hft_v2.zip")
    model.save(save_path)
    print(f"Training Complete. Saved to {save_path}")
    
    stats_path = os.path.join("models", "vec_normalize_v2.pkl")
    env.save(stats_path)
    print(f"Normalization statistics saved to {stats_path}")

if __name__ == "__main__":
    # Required on Windows for multi-processing safety
    multiprocessing.freeze_support()
    main()