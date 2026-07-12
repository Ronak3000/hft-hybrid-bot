import requests
from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/api/backtest", tags=["Historical Data"])

@router.get("/ohlcv")
async def get_historical_data(
    symbol: str = Query("BTC/USDT"),
    timeframe: str = Query("30m")
):
    """
    Fetches real historical candlestick data directly from Binance.
    """
    # Clean the symbol for Binance (e.g., BTC/USDT -> BTCUSDT)
    clean_symbol = symbol.replace("/", "").replace("-", "").upper()
    print(f"[Backtest Engine] Fetching real historical data for {clean_symbol}...")

    # Binance standard intervals. Map the UI timeframe to Binance format.
    interval_map = {
        "30m": "30m",
        "2h": "2h",
        "5h": "4h", # Fallback since Binance doesn't support 5h
        "4h": "4h"
    }
    
    interval = interval_map.get(timeframe, "30m")
    
    # Binance US REST API URL (Bypasses geoblock on Render)
    url = "https://api.binance.us/api/v3/klines"
    params = {
        "symbol": clean_symbol,
        "interval": interval,
        "limit": 500  # Pull the last 500 candles for a robust chart
    }

    try:
        response = requests.get(url, params=params)
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
            
        data = response.json()
        
        ohlcv_data = []
        for candle in data:
            ohlcv_data.append({
                "time": int(candle[0] / 1000), # TradingView requires Unix seconds, not milliseconds
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4])
            })
            
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "data": ohlcv_data
        }

    except Exception as e:
        print(f"[Backtest Engine] Error fetching data: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch historical data from exchange.")