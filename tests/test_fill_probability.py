import importlib.util
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from engine.market_data import CaptureWriter


@unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy is optional")
class FillProbeTests(unittest.TestCase):
    def test_frozen_forecast_applies_training_scaler_and_validation_sigmoid(self):
        import numpy as np
        from engine.research.fill_probability import INPUTS, FrozenFillModel

        report = {
            "inputs": INPUTS, "target": "any_simulated_fill_before_or_at_deadline",
            "weights": {"scaler_mean": [1] * 6, "scaler_scale": [2] * 6,
                        "coef": [1, 0, 0, 0, 0, 0], "intercept": 0,
                        "validation_sigmoid": [2, -1]},
            "settings": {"offsets": [0, 4]},
        }
        model = FrozenFillModel(report)
        actual = model.predict([[2, 0, 0, 0, 0, 0], [3, 0, 0, 0, 0, 0]])
        np.testing.assert_allclose(actual, [0.5, 1 / (1 + np.exp(-1))])

    def test_deadline_latency_and_censoring(self):
        from engine.research.fill_probability import probe_session
        from engine.research.trade_hawkes import load_arrivals
        from engine.simulation import SimulationConfig

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.jsonl"
            with CaptureWriter(path, {"venue": "binance_spot", "symbol": "BTCUSDT"}) as writer:
                writer.write("snapshot", {"lastUpdateId": 100, "bids": [["99", "1"]],
                                          "asks": [["101", "1"]]}, 1)
                def delta(timestamp, update):
                    writer.write("delta", {"e": "depthUpdate", "E": 10, "s": "BTCUSDT",
                                           "U": update, "u": update, "b": [], "a": []}, timestamp)
                def trade(timestamp, trade_id):
                    writer.write("trade", {"e": "trade", "E": 10, "T": 10, "s": "BTCUSDT",
                                           "t": trade_id, "p": "99", "q": "2", "m": True}, timestamp)
                delta(10, 101)
                trade(11, 201)  # too early: order activates at 12
                trade(13, 202)  # too late: deadline is 12
                delta(14, 102)
                trade(16, 203)  # exactly at activation and deadline
                delta(17, 103)  # the last two probes are right-censored
            rows, censored = probe_session(
                load_arrivals(path), config=SimulationConfig(order_latency_ns=2),
                tick_size=Decimal("1"), quantities=(Decimal("0.01"),),
                horizon_ns=2, stride=1, offsets=(0,),
            )
        self.assertEqual([row[1] for row in rows], [0, 0, 1, 0])
        self.assertEqual(censored, 2)

    def test_reliability_counts_and_brier(self):
        from engine.research.fill_probability import score_probabilities
        report = score_probabilities([0, 1, 1], [0, 0.5, 1])
        self.assertAlmostEqual(report["brier"], 0.25 / 3)
        self.assertEqual([bucket["decile"] for bucket in report["reliability"]], [0, 5, 9])
