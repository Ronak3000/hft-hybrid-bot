from __future__ import annotations

import csv
import json
import tempfile
import unittest
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from pathlib import Path

from engine.market_data import CaptureWriter
from engine.research import extract_feature_csv, iter_l2_features, verify_feature_csv


def _snapshot(update_id: int = 100) -> dict:
    return {
        "lastUpdateId": update_id,
        "bids": [["100", "10"], ["99", "5"]],
        "asks": [["102", "20"], ["103", "10"]],
    }


def _delta(first: int, final: int, bids=None, asks=None) -> dict:
    return {
        "e": "depthUpdate",
        "E": 1_700_000_000_000 + final,
        "s": "BTCUSDT",
        "U": first,
        "u": final,
        "b": bids or [],
        "a": asks or [],
    }


def _trade(trade_id: int) -> dict:
    return {
        "e": "trade",
        "E": 1_700_000_000_000,
        "s": "BTCUSDT",
        "t": trade_id,
        "p": "101",
        "q": "0.1",
        "T": 1_700_000_000_000,
        "m": False,
    }


def _capture(path: Path) -> None:
    with CaptureWriter(path, {"venue": "binance_spot", "symbol": "BTCUSDT"}) as writer:
        writer.write("snapshot", _snapshot(), 1)
        writer.write("trade", _trade(1), 1)
        writer.write(
            "delta",
            _delta(101, 101, bids=[["100", "12"]], asks=[["102", "18"]]),
            2,
        )
        writer.write("delta", _delta(100, 101, bids=[["1", "1"]]), 3)
        writer.write("delta", _delta(102, 102, bids=[["101", "4"]]), 4)


class CausalFeatureTests(unittest.TestCase):
    def test_hand_calculated_features_and_stale_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture.jsonl"
            _capture(capture)
            rows = list(iter_l2_features(capture, levels=2))

        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first.segment_id, 0)
        self.assertEqual(first.mid_price, Decimal("101"))
        self.assertEqual(first.spread, Decimal("2"))
        self.assertEqual(first.microprice, Decimal("100.8"))
        self.assertEqual(first.bid_depth, Decimal("17"))
        self.assertEqual(first.ask_depth, Decimal("28"))
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            expected_imbalance = Decimal("-11") / Decimal("45")
        self.assertEqual(first.depth_imbalance, expected_imbalance)
        self.assertEqual(first.ofi_l1, Decimal("4"))
        self.assertEqual(first.bid_levels_changed, 1)
        self.assertEqual(first.ask_levels_changed, 1)

        second = rows[1]
        self.assertEqual(second.best_bid, Decimal("101"))
        self.assertEqual(second.ofi_l1, Decimal("4"))
        self.assertEqual(second.update_id, 102)

    def test_public_trades_do_not_change_depth_only_features(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mixed = root / "mixed.jsonl"
            depth_only = root / "depth.jsonl"
            _capture(mixed)
            with CaptureWriter(
                depth_only, {"venue": "binance_spot", "symbol": "BTCUSDT"}
            ) as writer:
                writer.write("snapshot", _snapshot(), 1)
                writer.write(
                    "delta",
                    _delta(101, 101, bids=[["100", "12"]], asks=[["102", "18"]]),
                    2,
                )
                writer.write("delta", _delta(100, 101, bids=[["1", "1"]]), 3)
                writer.write("delta", _delta(102, 102, bids=[["101", "4"]]), 4)
            self.assertEqual(
                list(iter_l2_features(mixed, levels=2)),
                list(iter_l2_features(depth_only, levels=2)),
            )

    def test_gap_and_resnapshot_do_not_bridge_feature_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            with CaptureWriter(path, {"venue": "binance_spot", "symbol": "BTCUSDT"}) as writer:
                writer.write("snapshot", _snapshot(), 1)
                writer.write("delta", _delta(102, 102), 2)
                writer.write("gap", {"reason": "sequence_gap"}, 3)
                writer.write("snapshot", _snapshot(102), 4)
                writer.write("delta", _delta(103, 103, bids=[["100", "11"]]), 5)
            rows = list(iter_l2_features(path, levels=1))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].segment_id, 1)
        self.assertEqual(rows[0].update_id, 103)
        self.assertEqual(rows[0].ofi_l1, Decimal("1"))

    def test_csv_and_manifest_are_reproducible_and_source_linked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.jsonl"
            _capture(capture)
            first_path = root / "features-one.csv"
            second_path = root / "features-two.csv"
            first = extract_feature_csv(capture, first_path, levels=2)
            second = extract_feature_csv(capture, second_path, levels=2)

            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual(first["source_sha256"], second["source_sha256"])
            self.assertEqual(first["row_count"], 2)
            verify_feature_csv(first_path, capture)
            with first_path.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            self.assertNotIn("forward_return", rows[0])
            self.assertEqual(rows[0]["microprice"], "100.8")

    def test_global_decimal_precision_cannot_change_features(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture.jsonl"
            _capture(capture)
            normal = list(iter_l2_features(capture, levels=2))
            with localcontext() as context:
                context.prec = 6
                reduced_global_precision = list(iter_l2_features(capture, levels=2))
        self.assertEqual(normal, reduced_global_precision)

    def test_output_cannot_be_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.jsonl"
            output = root / "features.csv"
            _capture(capture)
            extract_feature_csv(capture, output)
            with self.assertRaises(FileExistsError):
                extract_feature_csv(capture, output)

    def test_feature_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.jsonl"
            output = root / "features.csv"
            _capture(capture)
            extract_feature_csv(capture, output)
            lines = output.read_text(encoding="utf-8").splitlines()
            lines[-1] = lines[-1].replace(",4,", ",999,", 1)
            output.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_feature_csv(output, capture)

    def test_manifest_row_count_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.jsonl"
            output = root / "features.csv"
            _capture(capture)
            extract_feature_csv(capture, output)
            manifest_path = Path(f"{output}.manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["row_count"] += 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_feature_csv(output, capture)

    def test_levels_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            list(iter_l2_features("unused", levels=0))


if __name__ == "__main__":
    unittest.main()
