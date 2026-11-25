from decimal import Decimal
import importlib.util
from pathlib import Path
import tempfile
import unittest

from engine.market_data import CaptureWriter


@unittest.skipUnless(importlib.util.find_spec("gymnasium"), "Gymnasium is optional")
class ArrivalQuoteTests(unittest.TestCase):
    def test_validation_size_match_uses_requested_side_weights_and_ties_down(self):
        from scripts.evaluate_arrival_rl import validation_matched_size

        rows = [
            {"requested_quote_quantity": Decimal("0.002"), "requested_sides": 2},
            {"requested_quote_quantity": Decimal("0.001"), "requested_sides": 2},
        ]
        self.assertEqual(validation_matched_size(rows, Decimal("0.001")), Decimal("0.0005"))
        self.assertIsNone(validation_matched_size([], Decimal("0.001")))

    def test_intensity_excludes_same_time_and_future_trades(self):
        import numpy as np
        from engine.research.trade_hawkes import Arrivals
        from engine.rl_trading.envs.arrival_quote_env import CausalTradeHistory

        events = Arrivals(Path("fixture"), "hash", ("binance_spot", "BTCUSDT"),
                          ((100, 0), (100, 1), (200, 1)))
        params = np.array([[2, 1, 0], [3, 0, 1]])
        history = CausalTradeHistory(events, decay=2, parameters=params)
        np.testing.assert_array_equal(history.intensity(100), [2, 3])
        np.testing.assert_allclose(history.intensity(200), [3, 4], atol=1e-6)
        np.testing.assert_allclose(history.intensity(201), [3, 5], atol=1e-6)
        with self.assertRaisesRegex(ValueError, "subcritical"):
            CausalTradeHistory(events, decay=0.5, parameters=params)

    def test_quote_grid_and_shared_replay_boundaries(self):
        import numpy as np
        from engine.research.fill_probability import INPUTS, FrozenFillModel
        from engine.research.trade_hawkes import Arrivals
        from engine.rl_trading.envs.arrival_quote_env import ArrivalQuoteEnv, CausalTradeHistory
        from engine.rl_trading.envs.queue_replay_env import QueueReplayEnv

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.jsonl"
            with CaptureWriter(path, {"venue": "binance_spot", "symbol": "BTCUSDT"}) as writer:
                writer.write("snapshot", {"lastUpdateId": 100, "bids": [["99", "1"]],
                                          "asks": [["101", "1"]]}, 100)
                writer.write("delta", {"e": "depthUpdate", "E": 1, "s": "BTCUSDT",
                                       "U": 101, "u": 101, "b": [], "a": []}, 101)
            history = CausalTradeHistory(
                Arrivals(path, "hash", ("binance_spot", "BTCUSDT"), ((200, 0),)),
                decay=2, parameters=np.array([[2, 1, 0], [3, 0, 1]]),
            )
            model = FrozenFillModel({
                "inputs": INPUTS, "target": "any_simulated_fill_before_or_at_deadline",
                "weights": {"scaler_mean": [0] * 6, "scaler_scale": [1] * 6,
                            "coef": [0] * 6, "intercept": 0, "validation_sigmoid": None},
                "settings": {"offsets": [0, 4]},
            })
            base = QueueReplayEnv((path,), tick_size="0.01", quantity="0.004")
            env = ArrivalQuoteEnv(base, (history,), model)
            try:
                observation, _ = env.reset()
                self.assertTrue(env.observation_space.contains(observation))
                np.testing.assert_allclose(observation[-6:], [2 / 3, 3 / 4, 0.5, 0.5, 0.5, 0.5])
                env.hide_fill_signal = True
                disabled, _ = env.reset()
                self.assertEqual(observation.shape, disabled.shape)
                np.testing.assert_array_equal(disabled[-4:], np.zeros(4))
                target = env.target([-1, 1, 0])
                self.assertEqual((target.bid_price, target.ask_price, target.quantity),
                                 (Decimal("99"), Decimal("182.92"), Decimal("0.002")))
                inactive = env.target([-1, 1, -1])
                self.assertIsNone(inactive.bid_price)
                self.assertIsNone(inactive.ask_price)
                with self.assertRaises(ValueError):
                    env.target([0, float("nan"), 0])
                self.assertFalse(env.step([-1, -1, 1])[2])
                _, _, terminated, truncated, info = env.step([-1, -1, 1])
                self.assertTrue(terminated)
                self.assertFalse(truncated)
                self.assertEqual(info["reason"], "end_of_capture")
            finally:
                env.close()
