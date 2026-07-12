import sys
import os
import time
import json
import requests
from celery import shared_task
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback

# Add the root directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from engine.rl_trading.envs.trading_env import TradingEnv
from worker.utils.data_downloader import download_binance_data 

class CeleryProgressCallback(BaseCallback):
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
        print(f"[Worker] Received job for {symbol} ({start_date} to {end_date})")
        
        # 1. Download Data Dynamically
        clean_symbol = symbol.replace("/", "").replace("-", "").upper()
        data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../data'))
        os.makedirs(data_dir, exist_ok=True)
        
        csv_filepath = os.path.join(data_dir, f"{clean_symbol}.csv")
        
        self.update_state(state='PENDING', meta={'status': 'Downloading historical data...'})
        download_binance_data(symbol, start_date, end_date, csv_filepath)

        # 2. Initialize the TRUE Environment with dynamic market parameters
        print(f"[Worker] Allocating C++ LOB. Base Size: {base_trade_size} | Max Inv: {max_inventory} | Penalty: {penalty_factor}")
        env = TradingEnv(
            symbol=symbol, start_date=start_date, end_date=end_date,
            starting_cash=starting_cash, base_trade_size=base_trade_size,
            max_inventory=max_inventory, maker_fee=maker_fee,
            penalty_factor=penalty_factor, kappa=kappa, live_mode=False
        )

        # 3. Initialize PPO Agent
        model = PPO("MlpPolicy", env, learning_rate=learning_rate, ent_coef=entropy_coef, verbose=0)

        # 4. Train with real-time telemetry connected to Redis
        total_steps = epochs * 5000 
        progress_callback = CeleryProgressCallback(self, total_timesteps=total_steps)
        model.learn(total_timesteps=total_steps, callback=progress_callback)

        # 5. Save the compiled model weights (.zip) AND local metadata sidecar (.json)
        save_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../engine/saved_models'))
        os.makedirs(save_dir, exist_ok=True)
        
        timestamp = int(time.time())
        model_filename = f"ppo_{clean_symbol}_{timestamp}.zip"
        save_path = os.path.join(save_dir, model_filename)
        model.save(save_path)
        print(f"[Worker] Compiled brain saved to: {save_path}")

        # --- NEW: LOCAL SIDECAR EXPORT (.json) ---
        json_filename = model_filename.replace(".zip", ".json")
        json_path = os.path.join(save_dir, json_filename)
        sidecar_payload = {
            "symbol": symbol.upper(),
            "max_inventory": float(max_inventory),
            "base_trade_size": float(base_trade_size),
            "kappa": float(kappa),
            "epochs": epochs,
            "learning_rate": learning_rate,
            "entropy_coef": entropy_coef,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(json_path, "w") as f:
            json.dump(sidecar_payload, f, indent=4)
        print(f"[Worker] Local metadata sidecar saved to: {json_path}")
        # ----------------------------------------

        # 6. Push Metadata to Supabase DB via internal API call
        print("[Worker] Registering model in database...")
        db_payload = {
            "symbol": symbol.upper(),
            "start_date": start_date,
            "end_date": end_date,
            "model_filename": model_filename,
            "hyperparameters": {
                "epochs": epochs, 
                "learning_rate": learning_rate, 
                "entropy_coef": entropy_coef,
                "kappa": float(kappa), 
                "base_trade_size": float(base_trade_size),
                "max_inventory": float(max_inventory)  # <-- FIXED: Explicitly added max_inventory!
            }
        }
        
        try:
            res = requests.post("http://localhost:8000/api/models/register", json=db_payload, timeout=10)
            print(f"[Worker] DB Registration Response: {res.status_code}")
        except Exception as api_err:
            print(f"[Worker Warning] Could not register model via HTTP API: {api_err}. (Local .json sidecar will act as backup)")

        print(f"[Worker] Job complete. Model and metadata locked in.")

        return {
            "status": "success",
            "model_file": model_filename,
            "sidecar_file": json_filename
        }

    except Exception as e:
        self.update_state(state='FAILURE', meta={'exc_type': type(e).__name__, 'exc_message': str(e)})
        raise e