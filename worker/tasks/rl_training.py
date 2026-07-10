import os
import time
from celery import shared_task
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
import gymnasium as gym
from gymnasium import spaces
import numpy as np

# ---------------------------------------------------------
# 1. TELEMETRY CALLBACK
# ---------------------------------------------------------
class CeleryProgressCallback(BaseCallback):
    """
    Hooks into the PPO training loop to send live progress updates 
    to Redis, which FastAPI then streams to the React UI.
    """
    def __init__(self, celery_task, total_timesteps, verbose=0):
        super().__init__(verbose)
        self.celery_task = celery_task
        self.total_timesteps = total_timesteps

    def _on_step(self) -> bool:
        # Push an update to Redis every 1024 steps to avoid choking the queue
        if self.num_timesteps % 1024 == 0:
            progress_pct = round((self.num_timesteps / self.total_timesteps) * 100, 2)
            
            # This updates the job state in Redis!
            self.celery_task.update_state(
                state='PROGRESS',
                meta={
                    'progress_percent': progress_pct,
                    'current_step': self.num_timesteps,
                    'total_steps': self.total_timesteps
                }
            )
        return True


# ---------------------------------------------------------
# 2. PLACEHOLDER ENVIRONMENT (Swap with your C++ Pybind Env)
# ---------------------------------------------------------
class DummyTradingEnv(gym.Env):
    """A minimal viable environment to test the Celery pipeline."""
    def __init__(self):
        super().__init__()
        self.action_space = spaces.Discrete(3) # Hold, Buy, Sell
        self.observation_space = spaces.Box(low=-1, high=1, shape=(5,), dtype=np.float32)
        self.step_count = 0

    def step(self, action):
        self.step_count += 1
        reward = np.random.normal(0, 1)
        done = self.step_count >= 1000
        return self.observation_space.sample(), reward, done, False, {}

    def reset(self, seed=None, options=None):
        self.step_count = 0
        return self.observation_space.sample(), {}


# ---------------------------------------------------------
# 3. THE CELERY TASK
# ---------------------------------------------------------
@shared_task(bind=True, name="worker.tasks.rl_training.train_ppo_model")
def train_ppo_model(self, symbol, start_date, end_date, epochs, learning_rate, entropy_coef):
    """
    The background worker function. 
    'bind=True' gives us access to 'self' to update the Celery task state.
    """
    try:
        print(f"[Worker] Starting training job for {symbol}. LR: {learning_rate}")
        
        # 1. Initialize Environment
        # IN PRODUCTION: env = YourCppTradingEnv(symbol, start_date, end_date)
        env = DummyTradingEnv()

        # 2. Initialize PPO Agent
        model = PPO(
            "MlpPolicy", 
            env, 
            learning_rate=learning_rate,
            ent_coef=entropy_coef,
            verbose=0
        )

        # 3. Train with real-time telemetry
        total_steps = epochs * 1000 # Example math
        progress_callback = CeleryProgressCallback(self, total_timesteps=total_steps)
        
        model.learn(total_timesteps=total_steps, callback=progress_callback)

        # 4. Save the compiled model weights
        save_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../engine/saved_models'))
        os.makedirs(save_dir, exist_ok=True)
        
        model_filename = f"ppo_{symbol.replace('/', '')}_{int(time.time())}.zip"
        save_path = os.path.join(save_dir, model_filename)
        model.save(save_path)

        print(f"[Worker] Job complete. Model saved to {save_path}")

        return {
            "status": "success",
            "model_file": model_filename,
            "final_reward": "..." # Extract from logger if needed
        }

    except Exception as e:
        self.update_state(state='FAILURE', meta={'exc_type': type(e).__name__, 'exc_message': str(e)})
        raise e