"""Exercise the training → saved model → historical → live API on real candles."""
import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import workbench
from api.main import app
from engine.market_data.candles import SYMBOLS


def smoke(symbol):
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    def at(minutes_ago):
        return (now - timedelta(minutes=minutes_ago)).isoformat()

    def body(response, status=200):
        if response.status_code != status:
            raise RuntimeError(f"{response.url}: {response.status_code} {response.text}")
        return response.json()

    def start(route, **values):
        return body(client.post(f"/api/{route}/start", json={"symbol": symbol, **values}), 202)["job_id"]

    def finish(route, job, *, timeout=300):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            result = body(client.get(f"/api/{route}/status/{job}"))
            if result["status"] == "completed":
                return result["result"]
            if result["status"] != "running":
                raise RuntimeError(f"{symbol} {route}: {result['message']}")
            time.sleep(1)
        raise RuntimeError(f"{symbol} {route}: timed out")

    key = "isolated-smoke-only"
    with TemporaryDirectory(prefix="apex-data-smoke-") as workdir, patch.object(
        workbench, "DATA", Path(workdir)
    ), patch.dict(os.environ, {"APEX_OPERATOR_TOKEN": key}), TestClient(
        app, headers={"Authorization": f"Bearer {key}"}
    ) as client:
        assert body(client.get("/health"))["exchange_order_routing"] is False
        train = start("training", source="candles", start=at(45), end=at(25), steps=32,
                      ppo={"n_steps": 16, "batch_size": 8, "n_epochs": 1, "hidden_width": 8})
        trained = finish("training", train)
        models = body(client.get(f"/api/models/{symbol}"))["models"]
        assert any(row["id"] == train and row["steps"] == 32 for row in models)
        print(f"{symbol}: trained and registered checkpoint on {trained['bars']} real bars", flush=True)

        route = "backtest"
        tested = finish(route, start(route, model_id=train, start=at(20), end=at(5)))
        assert tested["data_sha256"] != trained["data_sha256"] and len(tested["chart"]) >= 2
        print(f"{symbol}: tested frozen checkpoint on {tested['bars']} later bars"
              f" ({tested['fills']} paper fills)", flush=True)

        route = "live"
        live = start(route, model_id=train, seconds=125)
        assert body(client.post(f"/api/live/pause/{live}?paused=true"))["paused"]
        assert not body(client.post(f"/api/live/pause/{live}?paused=false"))["paused"]
        streamed = finish(route, live)
        if streamed["closed_bar_steps"] < 1:
            raise RuntimeError(f"{symbol}: connected but received no new closed bars")
        print(f"{symbol}: processed {streamed['closed_bar_steps']} newly closed live bars"
              f" ({streamed['fills']} paper fills); pause/resume accepted", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", choices=SYMBOLS, default="BTCUSDT")
    smoke(parser.parse_args().symbol)
