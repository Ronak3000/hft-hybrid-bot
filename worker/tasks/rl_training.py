import sys
import os
import time
from celery import shared_task
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback

# Add the root directory to sys.path so the worker can find 'engine'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from engine.rl_trading.envs.trading_env import TradingEnv

class CeleryProgressCallback(BaseCallback):
    """Hooks into PPO to send live progress updates to Redis."""
    def __init__(self, celery_task, total_timesteps, verbose=0):
        super().__init__(verbose)
        self.celery_task = celery_task
        self.total_timesteps = total_timesteps

    def _on_step(self) -> bool:
        if self.num_timesteps % 1024 == 0:
            progress_pct = round((self.num_timesteps / self.total_timesteps) * 100, 2)
            self.celery_task.update_state(
                state='PROGRESS',
                meta={
                    'progress_percent': progress_pct,
                    'current_step': self.num_timesteps,
                    'total_steps': self.total_timesteps
                }
            )
        return True

@shared_task(bind=True, name="worker.tasks.rl_training.train_ppo_model")
def train_ppo_model(self, symbol, start_date, end_date, epochs, learning_rate, entropy_coef,
                    starting_cash, base_trade_size, max_inventory, maker_fee, penalty_factor, kappa):
    try:
        print(f"[Worker] Allocating C++ LOB for {symbol} | Base Size: {base_trade_size} | Penalty: {penalty_factor}")
        
        # 1. Initialize the TRUE Environment with dynamic market parameters
        env = TradingEnv(
            symbol=symbol, start_date=start_date, end_date=end_date,
            starting_cash=starting_cash, base_trade_size=base_trade_size,
            max_inventory=max_inventory, maker_fee=maker_fee,
            penalty_factor=penalty_factor, kappa=kappa
        )

        # 2. Initialize PPO Agent
        model = PPO(
            "MlpPolicy", 
            env, 
            learning_rate=learning_rate,
            ent_coef=entropy_coef,
            verbose=0
        )

        # 3. Train with real-time telemetry connected to Redis
        total_steps = epochs * 5000 
        progress_callback = CeleryProgressCallback(self, total_timesteps=total_steps)
        
        print(f"[Worker] Initiating PPO training loop for {epochs} epochs...")
        model.learn(total_timesteps=total_steps, callback=progress_callback)

        # 4. Save the compiled model weights
        save_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../engine/saved_models'))
        os.makedirs(save_dir, exist_ok=True)
        
        model_filename = f"ppo_{symbol.replace('/', '')}_{int(time.time())}.zip"
        save_path = os.path.join(save_dir, model_filename)
        model.save(save_path)

        print(f"[Worker] Job complete. C++ memory freed. Model saved to {save_path}")

        return {
            "status": "success",
            "model_file": model_filename,
        }

    except Exception as e:
        self.update_state(state='FAILURE', meta={'exc_type': type(e).__name__, 'exc_message': str(e)})
        raise e