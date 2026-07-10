import json
import random
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import websockets

router = APIRouter(prefix="/ws", tags=["Live Trading"])

@router.websocket("/live/{symbol}")
async def live_trading_stream(websocket: WebSocket, symbol: str):
    """
    Proxies real-time tick data directly from Binance to the Next.js frontend.
    """
    await websocket.accept()
    
    # Binance requires lowercase symbols (e.g., 'btcusdt')
    binance_symbol = symbol.lower()
    binance_ws_url = f"wss://stream.binance.com:9443/ws/{binance_symbol}@trade"
    
    print(f"[Engine] Connecting to Live Binance Stream: {binance_ws_url}")
    
    # State variables for the mock AI execution (now hooked to REAL prices)
    cash = 1000000.0
    inventory = 0.0
    
    try:
        # Open a direct connection to Binance
        async with websockets.connect(binance_ws_url) as binance_ws:
            while True:
                # 1. Receive the real-time trade tick from Binance
                msg = await binance_ws.recv()
                data = json.loads(msg)
                
                # Binance @trade payload gives us "p" (price) and "T" (timestamp)
                real_price = float(data["p"])
                timestamp_ms = data["T"]
                
                # 2. Simulate our AI taking positions based on the REAL market ticks
                executions = []
                
                # Trigger a mock execution roughly 5% of the time to populate the terminal
                if random.random() < 0.05:
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
                        "price": round(real_price, 2),
                        "size": size,
                        "realized_pnl": round(pnl, 2)
                    })

                net_worth = cash + (inventory * real_price)

                # 3. Package the real data + AI telemetry and send to React
                payload = {
                    "timestamp": timestamp_ms,
                    "mid_price": real_price,
                    "net_worth": round(net_worth, 2),
                    "inventory_btc": round(inventory, 2),
                    "latest_executions": executions
                }
                
                await websocket.send_text(json.dumps(payload))
                
    except WebSocketDisconnect:
        print(f"[Engine] Client disconnected from {symbol} stream.")
    except Exception as e:
        print(f"[Engine] Stream Error: {e}")