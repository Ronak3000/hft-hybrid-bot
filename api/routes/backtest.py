import random
from datetime import datetime, timedelta
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/backtest", tags=["Historical Data"])

def generate_ohlc_data(start_price: float, periods: int, interval_minutes: int):
    """
    Generates a realistic random-walk candlestick dataset.
    """
    data = []
    current_price = start_price
    
    # Start time in the past
    current_time = datetime.utcnow() - timedelta(minutes=periods * interval_minutes)

    for _ in range(periods):
        # Determine OHLC physics
        open_price = current_price
        close_price = open_price + random.uniform(-50.0, 50.0)
        high_price = max(open_price, close_price) + random.uniform(0, 30.0)
        low_price = min(open_price, close_price) - random.uniform(0, 30.0)
        
        data.append({
            "time": int(current_time.timestamp()), # Lightweight charts requires Unix seconds
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2)
        })
        
        current_price = close_price
        current_time += timedelta(minutes=interval_minutes)

    return data

@router.get("/ohlcv")
async def get_historical_data(
    symbol: str = Query("BTC/USDT"),
    timeframe: str = Query("30m", regex="^(30m|2h|5h)$")
):
    """
    Returns historical candlestick data based on the requested timeframe.
    """
    timeframe_map = {
        "30m": {"periods": 100, "interval": 30},
        "2h": {"periods": 100, "interval": 120},
        "5h": {"periods": 100, "interval": 300},
    }
    
    config = timeframe_map.get(timeframe)
    ohlc = generate_ohlc_data(start_price=62500.0, periods=config["periods"], interval_minutes=config["interval"])
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "data": ohlc
    }