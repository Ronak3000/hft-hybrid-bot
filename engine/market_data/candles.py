"""Public Binance.US closed minute bars. No credentials or reconstructed ticks."""
import hashlib
import json
import math
from pathlib import Path
import time
import requests

URL = "https://api.binance.us/api/v3/klines"
MINUTE = 60000


SYMBOLS = ("BTCUSDT","ETHUSDT","SOLUSDT")


def _request_page(client, params, check):
    # Retry the same immutable window, never substitute a price or skip ahead.
    for attempt in range(3):
        check()
        try:
            response = client.get(URL, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            status = exc.response.status_code
            if status not in (408, 500, 502, 503, 504):
                raise ValueError(f"Binance.US candle request rejected (HTTP {status}).") from exc
        except (requests.ConnectionError, requests.Timeout):
            pass
        if attempt < 2:
            time.sleep(.5 * 2**attempt)
    raise ValueError("Binance.US candle feed unavailable after three attempts; no prices were substituted.")


def get_bars(symbol, first, stop, check=lambda: None, update=lambda msg: None, *, allow_gaps=False):
    if symbol not in SYMBOLS or first % MINUTE or stop % MINUTE or not first < stop <= int(time.time() * 1000):
        raise ValueError("Expected a supported symbol and completed UTC minutes.")
    rows = []
    cursor = first
    with requests.Session() as client:
        while cursor < stop:
            page_end = min(stop,cursor+1000*MINUTE)
            page = _request_page(client, dict(symbol=symbol, interval="1m", startTime=cursor,
                                               endTime=page_end-1, limit=1000), check)
            if not isinstance(page, list):
                raise ValueError("Invalid Binance.US response.")
            for row in page:
                ts = row[0]
                if ts < cursor or ts >= page_end or ts%MINUTE or row[6] != ts+MINUTE-1 or (not allow_gaps and ts != cursor):
                    raise ValueError("Incomplete or discontinuous Binance.US candle window.")
                o,h,l,c,v = map(float,row[1:6])
                if not all(math.isfinite(x) for x in (o,h,l,c,v)) or not 0 < l <= min(o,c) <= max(o,c) <= h or v < 0:
                    raise ValueError("Invalid exchange OHLCV values.")
                rows.append([ts,o,h,l,c,v])
                cursor = ts+MINUTE
            if cursor != page_end and not allow_gaps:
                raise ValueError("Incomplete or discontinuous Binance.US candle window.")
            cursor = page_end
            update(f"Downloaded {len(rows):,} of {(stop-first)//MINUTE:,} genuine 1-minute bars")
    return rows


def history(root, req, check, update):
    first, stop = (int(t.timestamp())*1000 for t in (req.start,req.end))
    if not 2 <= (stop-first)//MINUTE <= 366*1440:
        raise ValueError("Choose between 2 minutes and 366 days for candle replay.")
    rows = get_bars(req.symbol, first, stop, check, update,allow_gaps=True)
    if len(rows)<2:
        raise ValueError("Fewer than two real bars in the requested period.")
    raw = json.dumps(rows, separators=(",",":"), allow_nan=False).encode()
    if len(raw) > req.max_dataset_gb * 1024**3:
        raise ValueError("Candle dataset exceeds selected disk budget.")
    digest = hashlib.sha256(raw).hexdigest()
    folder = Path(root)/"candles"/req.symbol
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/(digest+".json")
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(path)
    elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("Cached candle bytes failed verification.")
    return rows, digest
