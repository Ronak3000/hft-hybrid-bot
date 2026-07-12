import os
import csv
import time
import random
import requests
from datetime import datetime

def download_binance_data(symbol: str, start_date: str, end_date: str, output_path: str):
    """
    Downloads historical data from Binance and synthesizes it into 
    bare-metal tick messages (Add, Cancel, Execute) for the C++ Engine.
    """
    clean_symbol = symbol.replace("/", "").replace("-", "").upper()
    print(f"[Downloader] Fetching Binance data for {clean_symbol}...")

    # Convert dates to milliseconds for the Binance API
    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

    url = "https://api.binance.us/api/v3/klines"
    all_klines = []
    current_ts = start_ts

    while current_ts < end_ts:
        params = {
            "symbol": clean_symbol,
            "interval": "1m",
            "startTime": current_ts,
            "endTime": end_ts,
            "limit": 1000
        }
        
        response = requests.get(url, params=params)
        if response.status_code != 200:
            print(f"[Warning] Binance API error: {response.text}")
            break
            
        data = response.json()
        if not data:
            break
            
        all_klines.extend(data)
        current_ts = data[-1][0] + 1 
        time.sleep(0.1)

    if not all_klines:
        raise ValueError(f"No data found for {symbol} in the given date range.")

    print(f"[Downloader] Fetched {len(all_klines)} minutes of market data. Compiling to C++ tick format...")

    order_id_counter = 1000
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        
        for kline in all_klines:
            timestamp_ms = kline[0]
            open_p, high_p, low_p, close_p = float(kline[1]), float(kline[2]), float(kline[3]), float(kline[4])
            volume = float(kline[5])
            
            prices = [open_p, high_p, low_p, close_p]
            
            # THE FIX: Scale the volume to strictly positive integers
            raw_vol = (volume / 4.0) if volume > 0 else 0.1
            base_vol = max(1, int(raw_vol * 10000))
            
            for p in prices:
                # 1. Add Liquidity
                side = 0 if random.random() > 0.5 else 1
                writer.writerow([timestamp_ms, 1, order_id_counter, side, int(p), base_vol])
                order_id_counter += 1
                
                # 2. Execute Trade
                timestamp_ms += 15 
                writer.writerow([timestamp_ms, 3, order_id_counter, side, int(p), base_vol])
                order_id_counter += 1

    print(f"[Downloader] Successfully wrote compiled tick data to {output_path}")
    return output_path