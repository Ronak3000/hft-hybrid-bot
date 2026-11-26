from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from engine.market_data import CaptureWriter


@unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy is optional")
class DepthWindowTests(unittest.TestCase):
    def test_ladders_rank_correctly_and_windows_stay_on_one_side_of_shallow_book(self):
        from engine.research.lob_depth import DepthWindows, load_depth_session, validate_depth_splits

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.jsonl"
            with CaptureWriter(path, {"venue": "binance_spot", "symbol": "BTCUSDT"}) as writer:
                writer.write("snapshot", {
                    "lastUpdateId": 100, "bids": [["98", "8"], ["99", "4"]],
                    "asks": [["103", "3"], ["101", "5"]],
                }, 10)
                for i, bids in enumerate(([["99", "3"]], [], [], [["98", "0"]],
                                          [["98", "8"]], [], [["100", "2"]]), 1):
                    writer.write("delta", {
                        "e": "depthUpdate", "s": "BTCUSDT", "E": 1000 + i,
                        "U": 100 + i, "u": 100 + i, "b": bids, "a": [],
                    }, 9 if i == 1 else 10 + i)
            session = load_depth_session(path, levels=2)
            self.assertEqual(list(session.ladders[0]), [99, 3, 101, 5, 98, 8, 103, 3])
            self.assertEqual(session.receive_ns, (12, 13, 15, 16, 17))
            self.assertEqual(session.groups, (0, 0, 1, 1, 1))
            windows = DepthWindows([session], lookback=2, horizon=1)
            self.assertEqual(len(windows), 1)
            features, target = windows[0]
            self.assertEqual(features.shape, (2, 8))
            self.assertEqual(target, 2)
            self.assertAlmostEqual(float(features[-1, 0]), -100)
            with self.assertRaisesRegex(ValueError, "reused"):
                validate_depth_splits({split: [session] for split in ("train", "validation", "test")})


@unittest.skipUnless(importlib.util.find_spec("torch"), "torch is optional")
class DepthModelTests(unittest.TestCase):
    def test_all_three_models_accept_full_depth_and_backpropagate(self):
        import torch
        from engine.research.lob_deep_models import MODEL_NAMES, make_depth_model

        previous = torch.get_num_threads()
        torch.set_num_threads(1)
        try:
            for name in MODEL_NAMES:
                with self.subTest(model=name):
                    net = make_depth_model(name, levels=10, lookback=16)
                    output = net(torch.ones(2, 16, 40))
                    self.assertEqual(tuple(output.shape), (2, 3))
                    output.sum().backward()
                    self.assertTrue(all(p.grad is not None for p in net.parameters()))
        finally:
            torch.set_num_threads(previous)
