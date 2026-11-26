"""Retired data paths must fail closed, never manufacture a market feed."""

from pathlib import Path
import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import training, live, backtest
except ModuleNotFoundError:
    FastAPI = None

ROOT = Path(__file__).resolve().parent.parent


class RemovedGeneratorsTests(unittest.TestCase):
    def test_removed_generators_and_fake_state_cannot_be_imported(self):
        removed = (
            "worker/utils/data_downloader.py", "engine/rl_trading/envs/trading_env.py",
            "scripts/train.py", "scripts/evaluate.py", "scripts/fetch_real_market_data.py",
            "web/src/store/useTradingStore.ts", "web/src/store/useTrainingStore.ts",
            "web/src/components/charts/LiveChart.tsx",
        )
        for path in removed:
            self.assertFalse((ROOT / path).exists(), path)
        for directory in ("api", "worker", "engine/rl_trading"):
            for path in (ROOT / directory).rglob("*.py"):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("import TradingEnv", source, str(path))
                self.assertNotIn("import random", source, str(path))
                self.assertNotIn("test_data.csv", source, str(path))
                self.assertNotIn("62500", source, str(path))

    def test_cpp_cannot_fabricate_live_depth_or_fallback_prices(self):
        source = (ROOT / "engine/backend_cpp/include/matching_engine.h").read_text()
        self.assertNotIn("inject_live_tick", source)
        self.assertNotIn("live_bid_depth_volume", source)
        self.assertNotIn("62500", source)
        self.assertIn("quiet_NaN", source)


@unittest.skipIf(FastAPI is None, "FastAPI test dependencies are not installed")
class RealDataRoutesTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        for router in (training.router, live.router, backtest.router):
            app.include_router(router)
        self.app = app
        self.client = TestClient(app)

    def test_unconfigured_remote_client_cannot_dispatch_training(self):
        response = self.client.post("/api/training/start", json={"symbol": "BTCUSDT"})
        self.assertIn(response.status_code, (401, 403))
        self.assertNotIn("job_id", response.json())
        self.assertEqual(self.client.get("/api/training/status/old-job").status_code, 404)

    def test_removed_history_and_engine_cannot_return_prices_or_results(self):
        self.assertEqual(self.client.get("/api/backtest/ohlcv").status_code, 404)
        self.assertEqual(self.client.post("/api/engine/deploy", json={}).status_code, 404)

    def test_real_routes_require_dates_or_specific_weights(self):
        from api.workbench import operator
        self.app.dependency_overrides[operator] = lambda: None
        for mode in ("training", "backtest", "live"):
            self.assertEqual(self.client.post(f"/api/{mode}/start", json={}).status_code, 422)

    def test_overlapping_window_fails_before_download_or_model_load(self):
        from datetime import datetime, timezone
        from unittest.mock import patch
        from api.workbench import Test, execute
        meta = {"archive_window": {"end": "2024-01-01T00:02:00Z"}}
        req = Test(model_id="demo", start=datetime(2024,1,1,tzinfo=timezone.utc),
                   end=datetime(2024,1,1,0,1,tzinfo=timezone.utc))
        with patch("api.workbench.models", return_value=[("demo","BTCUSDT",None,meta)]), patch("api.workbench.archive_dataset") as get:
            with self.assertRaisesRegex(ValueError, "after the end"):
                execute("backtest", req, "", lambda *args: None)
            get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
