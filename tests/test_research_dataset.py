from __future__ import annotations

import csv
import tempfile
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

from engine.market_data import CaptureWriter
from engine.research import (
    FEATURE_COLUMNS,
    build_forward_return_labels,
    chronological_split,
    extract_feature_csv,
    verify_labeled_csv,
    verify_split_csv,
)
from engine.research.l2_features import FEATURE_DECIMAL_CONTEXT


def _snapshot(update_id: int, bid: int = 100, ask: int = 102) -> dict:
    return {
        "lastUpdateId": update_id,
        "bids": [[str(bid), "10"]],
        "asks": [[str(ask), "20"]],
    }


def _delta(update_id: int, event_time: int, old_bid: int, old_ask: int) -> dict:
    return {
        "e": "depthUpdate",
        "E": event_time,
        "s": "BTCUSDT",
        "U": update_id,
        "u": update_id,
        "b": [[str(old_bid), "0"], [str(old_bid + 1), "10"]],
        "a": [[str(old_ask), "0"], [str(old_ask + 1), "20"]],
    }


def _capture_with_updates(path: Path, count: int = 30) -> None:
    with CaptureWriter(path, {"venue": "binance_spot", "symbol": "BTCUSDT"}) as writer:
        writer.write("snapshot", _snapshot(100), 1)
        for index in range(1, count + 1):
            writer.write(
                "delta",
                _delta(
                    100 + index,
                    1_000 + index * 100,
                    99 + index,
                    101 + index,
                ),
                1_000_000 + index,
            )


class LabelTests(unittest.TestCase):
    def test_timestamp_label_uses_first_observation_at_horizon(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.jsonl"
            features = root / "features.csv"
            labels = root / "labels.csv"
            _capture_with_updates(capture, count=5)
            extract_feature_csv(capture, features, levels=1)
            manifest = build_forward_return_labels(features, labels, horizon_ms=150)
            with labels.open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))
            verify_labeled_csv(labels, features)

        self.assertEqual(manifest["row_count"], 3)
        self.assertEqual(manifest["dropped_without_same_segment_future"], 2)
        self.assertEqual(rows[0]["label_target_event_time_ms"], "1300")
        self.assertEqual(rows[0]["label_realized_horizon_ms"], "200")
        with localcontext(FEATURE_DECIMAL_CONTEXT):
            expected = (Decimal("104") - Decimal("102")) / Decimal("102") * Decimal(10_000)
        self.assertEqual(Decimal(rows[0]["label_mid_return_bps"]), expected)
        self.assertTrue(all(column in rows[0] for column in FEATURE_COLUMNS))

    def test_labels_never_cross_snapshot_segments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.jsonl"
            features = root / "features.csv"
            labels = root / "labels.csv"
            with CaptureWriter(capture, {"venue": "binance_spot", "symbol": "BTCUSDT"}) as writer:
                writer.write("snapshot", _snapshot(100), 1)
                for index in range(1, 4):
                    writer.write(
                        "delta",
                        _delta(100 + index, 1_000 + index * 100, 99 + index, 101 + index),
                        index + 1,
                    )
                writer.write("snapshot", _snapshot(200, 200, 202), 10)
                for index in range(1, 4):
                    writer.write(
                        "delta",
                        _delta(200 + index, 2_000 + index * 100, 199 + index, 201 + index),
                        index + 10,
                    )
            extract_feature_csv(capture, features, levels=1)
            build_forward_return_labels(features, labels, horizon_ms=150)
            with labels.open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))

        self.assertEqual(len(rows), 2)
        self.assertEqual([row["segment_id"] for row in rows], ["0", "1"])


class ChronologicalSplitTests(unittest.TestCase):
    def test_splits_are_time_ordered_and_boundary_labels_are_purged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.jsonl"
            features = root / "features.csv"
            labels = root / "labels.csv"
            dataset = root / "dataset.csv"
            labels_second = root / "labels-second.csv"
            dataset_second = root / "dataset-second.csv"
            _capture_with_updates(capture)
            extract_feature_csv(capture, features, levels=1)
            build_forward_return_labels(features, labels, horizon_ms=100)
            manifest = chronological_split(labels, dataset, "0.6", "0.2")
            labels_manifest_second = build_forward_return_labels(
                features, labels_second, horizon_ms=100
            )
            manifest_second = chronological_split(
                labels_second, dataset_second, "0.6", "0.2"
            )
            with dataset.open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))
            verify_split_csv(dataset, labels)

        self.assertGreater(manifest["purged_boundary_crossing_labels"], 0)
        self.assertEqual(manifest["sha256"], manifest_second["sha256"])
        self.assertEqual(
            labels_manifest_second["source_feature_sha256"],
            manifest["source_feature_sha256"],
        )
        self.assertTrue(all(manifest["counts"][name] > 0 for name in manifest["counts"]))
        split_order = {"train": 0, "validation": 1, "test": 2}
        self.assertEqual(
            [split_order[row["split"]] for row in rows],
            sorted(split_order[row["split"]] for row in rows),
        )
        train_boundary = manifest["train_boundary_event_time_ms"]
        validation_boundary = manifest["validation_boundary_event_time_ms"]
        for row in rows:
            target = int(row["label_target_event_time_ms"])
            if row["split"] == "train":
                self.assertLess(target, train_boundary)
            elif row["split"] == "validation":
                self.assertLess(target, validation_boundary)

    def test_invalid_ratios_are_rejected_before_output(self) -> None:
        with self.assertRaises(ValueError):
            chronological_split("unused", "unused-output", "0.8", "0.2")


if __name__ == "__main__":
    unittest.main()
