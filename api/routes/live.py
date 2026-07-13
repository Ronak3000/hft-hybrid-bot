import json
import os
import sys
import asyncio
from datetime import datetime
from typing import cast, Dict, List, Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from pydantic import BaseModel
import websockets
from supabase import create_client

# --- AUTOMATIC PATH INJECTION ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.append(project_root)
# --------------------------------

# NOTE: stable_baselines3 (PyTorch), numpy, and TradingEnv are intentionally NOT
# imported here at module load time. PyTorch alone consumes ~350MB which would
# immediately OOM Render's 512MB free tier. They are lazily imported inside
# boot_engine_and_model() only when a user actually clicks "Deploy Strategy".
from api.core.database import supabase as supabase_client

# Storage client: uses service_role key to bypass RLS on the private 'models' bucket.
# Falls back to the regular anon client if SUPABASE_SERVICE_KEY is not set.
_service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
_supabase_url = os.environ.get("SUPABASE_URL", "")
storage_client = (
    create_client(_supabase_url, _service_key)
    if _service_key and _supabase_url
    else supabase_client
)

router = APIRouter(tags=["Institutional Live Daemon"])

# =====================================================================
# 1. THE STATE STORE & QUANT DAEMON MANAGER
# =====================================================================
class EngineState:
    def __init__(self, symbol: str, model_filename: str, env: Any, agent: Any, obs: Any, max_inventory: float, base_trade_size: float):
        self.symbol: str = symbol
        self.model_filename: str = model_filename
        self.is_running: bool = False
        self.is_quoting: bool = True  # Leave/Enter Market control flag
        
        self.env: Any = env
        self.agent: Any = agent
        self.obs: Any = obs
        
        self.max_inventory: float = max_inventory
        self.base_trade_size: float = base_trade_size
        
        # In-Memory Telemetry Cache
        self.latest_price: float = 0.0
        self.net_worth: float = 1000000.0
        self.inventory: float = 0.0
        self.executions: List[Dict[str, Any]] = []
        self.chart_buffer: List[Dict[str, Any]] = []  
        
        # Async Control
        self.stop_signal = asyncio.Event()
        self.new_tick_event = asyncio.Event()
        self.latest_tick_data: Dict[str, Any] = {"price": 0.0, "volume": 0.0, "is_buyer_maker": False, "timestamp": 0}
        self.subscribers: List[WebSocket] = []

class QuantDaemonManager:
    def __init__(self):
        self.daemons: Dict[str, EngineState] = {}

    def get_status(self, symbol: str) -> Dict[str, Any]:
        clean_sym = symbol.upper().replace("/", "").replace("-", "")
        if clean_sym in self.daemons and self.daemons[clean_sym].is_running:
            state = self.daemons[clean_sym]
            return {
                "status": "LIVE",
                "is_quoting": state.is_quoting,
                "symbol": symbol,
                "model_filename": state.model_filename,
                "max_inventory": state.max_inventory,
                "base_trade_size": state.base_trade_size,
                "net_worth": state.net_worth,
                "inventory": state.inventory,
                "latest_price": state.latest_price,
                "recent_executions": state.executions[-50:],
                "chart_buffer": state.chart_buffer[-300:]
            }
        return {"status": "OFFLINE", "symbol": symbol}

    async def stop_daemon(self, symbol: str) -> bool:
        clean_sym = symbol.upper().replace("/", "").replace("-", "")
        if clean_sym in self.daemons:
            print(f"[Daemon] Terminating autonomous execution for {clean_sym}...")
            self.daemons[clean_sym].stop_signal.set()
            self.daemons[clean_sym].is_running = False
            for ws in self.daemons[clean_sym].subscribers:
                try:
                    await ws.send_text(json.dumps({"status": "OFFLINE"}))
                    await ws.close()
                except Exception:
                    pass
            self.daemons[clean_sym].subscribers.clear()
            del self.daemons[clean_sym]
            return True
        return False

manager = QuantDaemonManager()

# =====================================================================
# 2. UNIVERSAL HYPERPARAMETER LOADER
# =====================================================================
def fetch_model_hyperparameters(model_filename: str):
    max_inv = 10.0
    base_sz = 0.5
    kappa_val = 1.5
    
    # 1. First try Supabase DB (safely handling both dictionary and JSON string formats)
    if supabase_client:
        try:
            res = supabase_client.table("trained_models").select("*").eq("model_filename", model_filename).execute()
            if res.data and len(res.data) > 0:
                # Tell Pylance this row is strictly a dictionary, not a JSON primitive union!
                row = cast(Dict[str, Any], res.data[0])
                params = row.get("hyperparameters", {})
                
                if isinstance(params, str):
                    try: params = json.loads(params)
                    except Exception: params = {}
                    
                if isinstance(params, dict):
                    # Use str(...) before float(...) so Pylance ConvertibleToFloat is satisfied
                    if "max_inventory" in params and params["max_inventory"] is not None:
                        max_inv = float(str(params["max_inventory"]))
                    if "base_trade_size" in params and params["base_trade_size"] is not None:
                        base_sz = float(str(params["base_trade_size"]))
                    if "kappa" in params and params["kappa"] is not None:
                        kappa_val = float(str(params["kappa"]))
                print(f"[Daemon] Inherited Supabase DB params: MaxInv={max_inv}, BaseSize={base_sz}, Kappa={kappa_val}")
                return max_inv, base_sz, kappa_val
        except Exception as e:
            print(f"[Daemon Warning] Supabase DB lookup failed: {e}")

    # 2. Fallback: Check local JSON metadata file in saved_models
    try:
        base_name = model_filename.replace(".zip", "")
        local_json_path = os.path.abspath(os.path.join(os.path.dirname(__file__), f"../../engine/saved_models/{base_name}.json"))
        if not os.path.exists(local_json_path):
            local_json_path = os.path.abspath(os.path.join(os.path.dirname(__file__), f"../../engine/saved_models/{model_filename}.json"))
            
        if os.path.exists(local_json_path):
            with open(local_json_path, "r") as f:
                params = json.load(f)
            if isinstance(params, dict):
                if "max_inventory" in params and params["max_inventory"] is not None:
                    max_inv = float(str(params["max_inventory"]))
                if "base_trade_size" in params and params["base_trade_size"] is not None:
                    base_sz = float(str(params["base_trade_size"]))
                if "kappa" in params and params["kappa"] is not None:
                    kappa_val = float(str(params["kappa"]))
            print(f"[Daemon] Inherited Local JSON params: MaxInv={max_inv}, BaseSize={base_sz}, Kappa={kappa_val}")
    except Exception as e:
        print(f"[Daemon Warning] Local JSON lookup failed: {e}")

    return max_inv, base_sz, kappa_val

# =====================================================================
# 3. BACKGROUND WORKER HELPERS
# =====================================================================
def _ensure_model_downloaded(model_filename: str, model_path: str):
    """Download model .zip (and .json sidecar) from Supabase Storage if not present locally."""
    if os.path.exists(model_path):
        return  # Already present, nothing to do

    if not storage_client:
        raise FileNotFoundError(
            f"Model '{model_filename}' not found locally and Supabase is unavailable to download it."
        )

    print(f"[Daemon] Model not found locally — downloading '{model_filename}' from Supabase Storage...")
    try:
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        response = storage_client.storage.from_("models").download(model_filename)
        with open(model_path, "wb") as f:
            f.write(response)
        print(f"[Daemon] Model downloaded successfully to {model_path}")
    except Exception as e:
        # Print the REAL error so it appears in Render logs
        print(f"[Daemon ERROR] Supabase Storage download failed: {type(e).__name__}: {e}")
        raise FileNotFoundError(
            f"Failed to download model '{model_filename}' from Supabase Storage bucket 'models': {e}"
        )

    # Also download the .json sidecar (best-effort, non-fatal)
    json_filename = model_filename.replace(".zip", "") + ".json"
    json_path = os.path.join(os.path.dirname(model_path), json_filename)
    if not os.path.exists(json_path):
        try:
            json_bytes = storage_client.storage.from_("models").download(json_filename)
            with open(json_path, "wb") as f:
                f.write(json_bytes)
            print(f"[Daemon] Metadata sidecar downloaded to {json_path}")
        except Exception:
            pass  # Non-fatal: hyperparams already loaded from Supabase DB 


def boot_engine_and_model(symbol: str, model_filename: str):
    # Lazy imports — deferred until first Deploy click to avoid OOM at startup.
    import numpy as np  # noqa: F401 (used in execute_rl_step via module-level cache)
    from stable_baselines3 import PPO
    from engine.rl_trading.envs.trading_env import TradingEnv

    model_path = os.path.abspath(os.path.join(os.path.dirname(__file__), f"../../engine/saved_models/{model_filename}"))
    max_inv, base_sz, kappa_val = fetch_model_hyperparameters(model_filename)

    # Auto-download the model from Supabase Storage if running on an ephemeral server
    _ensure_model_downloaded(model_filename, model_path)

    env = TradingEnv(symbol=symbol.upper(), max_inventory=max_inv, base_trade_size=base_sz, kappa=kappa_val, live_mode=True)
    agent = PPO.load(model_path, env=env)
    obs, _ = env.reset()
    return env, agent, obs, max_inv, base_sz

def execute_rl_step(env: Any, agent: Any, obs: Any, tick_data: Dict[str, Any], is_quoting: bool):
    import numpy as np
    raw_env = cast(Any, env.unwrapped)
    raw_env.inject_live_tick(
        price=float(str(tick_data["price"])), 
        volume=float(str(tick_data["volume"])), 
        is_buyer_maker=bool(tick_data["is_buyer_maker"])
    )
    
    # Strictly synchronize quoting state directly into environment physics
    raw_env.is_quoting = is_quoting  
    
    if not is_quoting:
        action = np.array([0.5, 10.0], dtype=np.float32)
    else:
        action, _ = agent.predict(obs, deterministic=True)
        
    next_obs, reward, terminated, truncated, info = env.step(action)
    return next_obs, reward, terminated, truncated, info

async def run_autonomous_daemon(state: EngineState):
    binance_symbol = state.symbol.lower().replace("/", "").replace("-", "")
    binance_ws_url = f"wss://stream.binance.com:443/ws/{binance_symbol}@trade"
    
    async def producer():
        try:
            async with websockets.connect(binance_ws_url) as binance_ws:
                print(f"[Daemon] Connected to live exchange feed: {binance_ws_url}")
                while not state.stop_signal.is_set():
                    msg = await binance_ws.recv()
                    data = json.loads(msg)
                    state.latest_tick_data = {
                        "price": float(str(data["p"])),
                        "volume": float(str(data["q"])),
                        "is_buyer_maker": bool(data["m"]),
                        "timestamp": int(str(data["T"]))
                    }
                    state.new_tick_event.set()
        except Exception as e:
            print(f"[Daemon Producer Error] {e}")
            state.stop_signal.set()

    async def consumer():
        is_first_tick = True
        try:
            while not state.stop_signal.is_set():
                await state.new_tick_event.wait()
                state.new_tick_event.clear()
                current_tick = dict(state.latest_tick_data)
                
                if is_first_tick:
                    print(f"[Daemon] Seeding initial market alignment for {state.symbol}: ${current_tick['price']}")
                    raw_env = cast(Any, state.env.unwrapped)
                    raw_env.live_price = float(str(current_tick["price"]))
                    state.obs, _ = await asyncio.to_thread(state.env.reset)
                    is_first_tick = False
                
                state.obs, reward, terminated, truncated, info = await asyncio.to_thread(
                    execute_rl_step, state.env, state.agent, state.obs, current_tick, state.is_quoting
                )
                
                state.latest_price = float(str(current_tick["price"]))
                state.net_worth = round(float(str(info.get("net_worth", 1000000.0))), 2)
                state.inventory = round(float(str(info.get("inventory", 0.0))), 2)
                
                new_execs = cast(List[Dict[str, Any]], info.get("latest_executions", []))
                if new_execs:
                    for ex in new_execs:
                        ex["time"] = current_tick["timestamp"]
                        state.executions.append(ex)
                    state.executions = state.executions[-100:]
                
                payload = {
                    "timestamp": current_tick["timestamp"],
                    "mid_price": state.latest_price,
                    "net_worth": state.net_worth,
                    "inventory_btc": state.inventory,
                    "is_quoting": state.is_quoting,
                    "latest_executions": new_execs
                }
                
                state.chart_buffer.append(payload)
                if len(state.chart_buffer) > 500:
                    state.chart_buffer.pop(0)
                
                if state.subscribers:
                    dead_sockets = []
                    msg_str = json.dumps(payload)
                    for ws in state.subscribers:
                        try:
                            await ws.send_text(msg_str)
                        except Exception:
                            dead_sockets.append(ws)
                    for dead in dead_sockets:
                        if dead in state.subscribers:
                            state.subscribers.remove(dead)
                            
                if terminated or truncated:
                    print(f"[Daemon] Risk circuit breaker triggered for {state.symbol}. Halting daemon.")
                    state.stop_signal.set()
                    break
        except Exception as e:
            print(f"[Daemon Consumer Error] {e}")
            state.stop_signal.set()

    prod_task = asyncio.create_task(producer())
    cons_task = asyncio.create_task(consumer())
    await state.stop_signal.wait()
    prod_task.cancel()
    cons_task.cancel()
    await asyncio.gather(prod_task, cons_task, return_exceptions=True)
    print(f"[Daemon] {state.symbol} execution engine completely shut down.")

# =====================================================================
# 4. CONTROL PLANE (REST APIs)
# =====================================================================
class DeployRequest(BaseModel):
    symbol: str
    model_filename: str

@router.post("/api/engine/deploy")
async def deploy_engine(req: DeployRequest):
    clean_sym = req.symbol.upper().replace("/", "").replace("-", "")
    if clean_sym in manager.daemons and manager.daemons[clean_sym].is_running:
        return {"status": "success", "message": "Daemon already active.", "symbol": req.symbol}
    
    print(f"[Control Plane] Allocating C++ bare-metal daemon for {req.symbol}...")
    try:
        env, agent, obs, max_inv, base_sz = await asyncio.to_thread(boot_engine_and_model, req.symbol, req.model_filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"C++ allocation failure: {str(e)}")
        
    state = EngineState(
        symbol=req.symbol, 
        model_filename=req.model_filename, 
        env=env, 
        agent=agent, 
        obs=obs, 
        max_inventory=max_inv, 
        base_trade_size=base_sz
    )
    state.is_running = True
    state.is_quoting = True
    
    manager.daemons[clean_sym] = state
    asyncio.create_task(run_autonomous_daemon(state))
    
    return {"status": "success", "message": f"Autonomous daemon deployed for {req.symbol}", "max_inventory": max_inv, "base_trade_size": base_sz}

@router.post("/api/engine/toggle_quoting")
async def toggle_quoting(symbol: str = Query(...)):
    """
    Leave Market / Enter Market toggle. Pauses quote placement without stopping the daemon.
    """
    clean_sym = symbol.upper().replace("/", "").replace("-", "")
    if clean_sym not in manager.daemons or not manager.daemons[clean_sym].is_running:
        raise HTTPException(status_code=404, detail="No active daemon found for this symbol.")
    
    state = manager.daemons[clean_sym]
    state.is_quoting = not state.is_quoting
    
    # Sync immediately down to the physical environment instance
    raw_env = cast(Any, state.env.unwrapped)
    raw_env.is_quoting = state.is_quoting
    
    status_str = "ENTERED MARKET (Quoting Active)" if state.is_quoting else "LEFT MARKET (Quoting Paused)"
    print(f"[Control Plane] {symbol}: {status_str}")
    return {"status": "success", "is_quoting": state.is_quoting, "message": status_str}

@router.post("/api/engine/stop")
async def stop_engine(symbol: str = Query(...)):
    stopped = await manager.stop_daemon(symbol)
    if not stopped:
        raise HTTPException(status_code=404, detail="No active daemon found for this symbol.")
    return {"status": "success", "message": f"Daemon terminated for {symbol}"}

@router.get("/api/engine/status/{symbol}")
async def get_engine_status(symbol: str):
    return manager.get_status(symbol)

# =====================================================================
# 5. DATA PLANE (TELEMETRY SUBSCRIBER WEBSOCKET)
# =====================================================================
@router.websocket("/ws/live/{symbol}")
async def telemetry_subscriber(websocket: WebSocket, symbol: str):
    await websocket.accept()
    clean_sym = symbol.upper().replace("/", "").replace("-", "")
    
    if clean_sym not in manager.daemons or not manager.daemons[clean_sym].is_running:
        await websocket.send_text(json.dumps({"error": f"No active daemon running for {symbol}. Click Deploy Strategy first."}))
        await websocket.close()
        return

    state = manager.daemons[clean_sym]
    state.subscribers.append(websocket)
    
    try:
        recovery_payload = {
            "type": "RECOVERY_BUFFER",
            "net_worth": state.net_worth,
            "inventory_btc": state.inventory,
            "mid_price": state.latest_price,
            "max_inventory": state.max_inventory,
            "base_trade_size": state.base_trade_size,
            "is_quoting": state.is_quoting,
            "chart_buffer": state.chart_buffer,
            "recent_executions": state.executions[-50:]
        }
        await websocket.send_text(json.dumps(recovery_payload))
        
        while True:
            await websocket.receive_text() 
            
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in state.subscribers:
            state.subscribers.remove(websocket)