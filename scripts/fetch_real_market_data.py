import csv
import requests
import time
import sys
import os
from pathlib import Path

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
build_path = project_root / "backend_cpp" / "build"

for path in (project_root, build_path):
    sys.path.insert(0, str(path))

def fetch_massive_binance_data(filename="test_data.csv", target_trades=400000):
    limit_per_request = 1000
    requests_needed = target_trades // limit_per_request

    print(f"Targeting {target_trades:,} real Binance market executions.")
    print(f"Fetching in {requests_needed} paginated API batches...")

    # 1. Ping Binance for the absolute latest trade ID
    try:
        initial_res = requests.get("https://api.binance.com/api/v3/aggTrades?symbol=BTCUSDT&limit=1")
        initial_res.raise_for_status()
        latest_id = initial_res.json()[0]['a']
    except Exception as e:
        print(f"CRITICAL: Failed to connect to Binance. {e}")
        return

    # 2. Wind the clock back
    current_from_id = latest_id - target_trades
    total_engine_rows_generated = 0
    order_id = 1

    # Save to the root directory
    root_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    filepath = os.path.join(root_dir, filename)

    with open(filepath, mode='w', newline='') as file:
        writer = csv.writer(file)
        # MUST have NO header for the C++ std::from_chars parser to work at max speed!
        
        # 3. High-Speed Paginated API Loop
        for batch in range(requests_needed):
            url = f"https://api.binance.com/api/v3/aggTrades?symbol=BTCUSDT&limit={limit_per_request}&fromId={current_from_id}"
            
            try:
                res = requests.get(url)
                res.raise_for_status()
                trades = res.json()
            except Exception as e:
                print(f"\nAPI Error on batch {batch}: {e}. Retrying in 5s...")
                time.sleep(5)
                continue

            if not trades:
                break

            for trade in trades:
                timestamp = int(trade['T']) 
                
                # CRITICAL: Round to nearest whole dollar to fit inside the 1,000,000 C++ Memory Slab!
                price = int(round(float(trade['p'])))     
                
                # Scale BTC quantity (0.01 BTC = 1 unit)
                qty = max(1, int(float(trade['q']) * 100))

                # If m=true, buyer is maker, meaning the aggressor was a SELLER (Side 1)
                aggressor_side = 1 if trade['m'] else 0 

                # Feed the real execution into the C++ Engine
                writer.writerow([timestamp, 1, order_id, aggressor_side, price, qty])
                
                order_id += 1
                total_engine_rows_generated += 1

            # Update ID pointer for the next pagination request
            current_from_id = trades[-1]['a'] + 1

            # Console Loading Bar
            progress = (batch + 1) / requests_needed * 100
            sys.stdout.write(f"\r[Data Pipeline] [{'=' * int(progress // 2)}{' ' * (50 - int(progress // 2))}] {progress:.1f}% ({total_engine_rows_generated:,} rows)")
            sys.stdout.flush()

            time.sleep(0.1) # Respect API rate limits

    print(f"\n\nSuccess! Reconstructed Real Limit Order Book saved to {filepath}.")

if __name__ == "__main__":
    fetch_massive_binance_data()