import asyncio
import json
import random
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/ws", tags=["Live Trading"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[Engine] Client connected. Total active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print("[Engine] Client disconnected.")

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except RuntimeError:
                pass

manager = ConnectionManager()

async def hft_engine_simulator():
    """
    Simulates the high-frequency data stream from the C++ matching engine.
    """
    price = 62500.0
    cash = 10000.0
    inventory = 0.0

    while True:
        await asyncio.sleep(0.1) # 100ms throttle
        
        if not manager.active_connections:
            continue

        price += random.choice([-2.0, -1.0, 0.0, 1.0, 2.0])
        
        executions = []
        if random.random() < 0.40:
            side = random.choice(["BUY", "SELL"])
            size = 0.5
            pnl = random.uniform(-1.0, 3.5) 
            
            if side == "BUY":
                inventory += size
            else:
                inventory -= size
                
            cash += pnl
            
            executions.append({
                "time": datetime.utcnow().isoformat() + "Z",
                "side": side,
                "price": round(price, 2),
                "size": size,
                "realized_pnl": round(pnl, 2)
            })

        net_worth = cash + (inventory * price)

        payload = {
            "timestamp": int(datetime.utcnow().timestamp() * 1000),
            "mid_price": round(price, 2),
            "net_worth": round(net_worth, 2),
            "inventory_btc": round(inventory, 2),
            "latest_executions": executions
        }

        await manager.broadcast(json.dumps(payload))

@router.websocket("/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            print(f"[Engine] Received command: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)