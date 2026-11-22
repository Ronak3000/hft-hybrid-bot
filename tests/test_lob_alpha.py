from __future__ import annotations

import importlib.util
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from engine.market_data import CaptureWriter
from engine.research.l2_features import extract_feature_csv
from engine.research.lob_alpha import INPUTS, evaluate, examples, load_session, validate_splits


def _feature_row(segment, time, mid, ofi):
    return dict.fromkeys(INPUTS, "0") | {
        "segment_id": str(segment), "received_time_ns": str(time),
        "mid_price": str(mid), "ofi_l1": str(ofi),
    }


class LobAlphaTests(unittest.TestCase):
    def test_labels_do_not_cross_gap_and_inputs_are_current_only(self):
        rows = [
            _feature_row(0, 1, "100.00000000000000000001", 3),
            _feature_row(0, 2, "100.00000000000000000002", 99),
            _feature_row(1, 3, 70, 4),
            _feature_row(1, 4, 69, 98),
        ]
        self.assertEqual(list(examples(rows, 1)), [
            ((3.0, 0.0, 0.0, 0.0), 1, 1e-9),
            ((4.0, 0.0, 0.0, 0.0), -1, 1e-9),
        ])
        self.assertEqual(list(examples(rows, 2)), [])

    def test_temporal_window_uses_only_past_and_current_rows_within_segment(self):
        rows = [_feature_row(i // 3, i, 100 + i, i) for i in range(6)]
        windows = list(examples(rows, 1, lookback=2))
        self.assertEqual([(features[0], features[4], label) for features, label, _ in windows],
                         [(0.0, 1.0, 1), (3.0, 4.0, 1)])

    def _sessions(self, root):
        sessions = {}
        for offset, split in enumerate(("train", "validation", "test"), 1):
            capture = root / f"{split}.jsonl"
            feature = root / f"{split}.csv"
            start = offset * 10_000_000_000
            with CaptureWriter(capture, {"venue": "binance_spot", "symbol": "BTCUSDT"}) as writer:
                writer.write("snapshot", {
                    "lastUpdateId": 100, "bids": [["100", "2"]], "asks": [["103", "2"]],
                }, start)
                for i, bids in enumerate(([["101", "2"]], [["101", "0"]], [], [["101", "4"]]), 1):
                    writer.write("delta", {
                        "e": "depthUpdate", "s": "BTCUSDT", "E": start // 1_000_000 + i,
                        "U": 100 + i, "u": 100 + i, "b": bids, "a": [],
                    }, start + i * 100_000_000)
            extract_feature_csv(capture, feature)
            sessions[split] = [load_session(feature)]
        return sessions

    def test_rejects_duplicate_source_and_reversed_splits(self):
        with tempfile.TemporaryDirectory() as folder:
            splits = self._sessions(Path(folder))
            validate_splits(splits)
            with self.assertRaisesRegex(ValueError, "chronological"):
                validate_splits(splits | {"train": splits["test"], "test": splits["train"]})
            with self.assertRaisesRegex(ValueError, "reused"):
                validate_splits(splits | {"test": splits["train"]})

    @unittest.skipUnless(importlib.util.find_spec("sklearn"), "optional alpha dependency")
    def test_report_runs_on_verified_session_fixtures(self):
        with tempfile.TemporaryDirectory() as folder:
            splits = self._sessions(Path(folder))
            report = evaluate(splits, (1,))
        result = report["horizons"]["1"]
        self.assertEqual(result["training_support"], [1, 1, 1])
        logistic = result["test"]["pooled"]["logistic"]
        self.assertEqual(logistic["support"], [1, 1, 1])
        self.assertEqual(sum(map(sum, logistic["confusion_matrix"])), 3)
        self.assertAlmostEqual(result["test"]["sessions"][0]["mean_label_delay_seconds"], 0.1)

    @unittest.skipUnless(importlib.util.find_spec("sklearn"), "optional alpha dependency")
    def test_temporal_report_scores_identical_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            report = evaluate(self._sessions(Path(folder)), (1,), lookback=2)
        scores = report["horizons"]["1"]["test"]["pooled"]
        self.assertEqual(set(scores), {"majority", "microprice_sign", "logistic", "temporal_mlp"})
        self.assertEqual({tuple(score["support"]) for score in scores.values()}, {(0, 1, 1)})

    @unittest.skipUnless(importlib.util.find_spec("sklearn"), "optional alpha dependency")
    def test_paired_replay_joins_depth_updates_and_zero_width_matches_baseline(self):
        from engine.research.alpha_quotes import evaluate_alpha_quotes
        from engine.simulation import AvellanedaStoikovPolicy, SimulationConfig

        d = Decimal
        policy = AvellanedaStoikovPolicy(d("0.01"), d("0.001"), d("0.001"), d("0.5"), d("1"), d("60"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            splits = self._sessions(root)
            result = evaluate_alpha_quotes(
                splits["train"], splits["validation"], root / "test.jsonl", root / "test.csv",
                policy=policy, config=SimulationConfig(), horizon=1, widen_ticks=0,
                markout_horizons_ns=(100_000_000,),
            )
        self.assertEqual(result["matched_updates"], 4)
        self.assertEqual(result["avellaneda_stoikov"], result["alpha_widened"])
