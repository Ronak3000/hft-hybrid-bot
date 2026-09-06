from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

from engine.market_data.l2 import (
    ApplyStatus,
    CaptureIntegrityError,
    CaptureWriter,
    L2Book,
    SchemaError,
    parse_binance_delta,
    parse_binance_snapshot,
    parse_binance_trade,
    replay_capture,
    verify_capture,
)


def snapshot(update_id: int = 100) -> dict:
    return {
        "lastUpdateId": update_id,
        "bids": [["100.00", "2.5"], ["99.00", "4"]],
        "asks": [["101.00", "3"], ["102.00", "5"]],
    }


def delta(first: int, final: int, bids=None, asks=None) -> dict:
    return {
        "e": "depthUpdate",
        "E": 1_700_000_000_000,
        "s": "BTCUSDT",
        "U": first,
        "u": final,
        "b": bids or [],
        "a": asks or [],
    }


def trade(trade_id: int, *, buyer_is_maker: bool = False) -> dict:
    return {
        "e": "trade",
        "E": 1_700_000_000_001,
        "s": "BTCUSDT",
        "t": trade_id,
        "p": "100.2500",
        "q": "0.0300",
        "T": 1_700_000_000_000,
        "m": buyer_is_maker,
        "M": True,
    }


class L2SchemaTests(unittest.TestCase):
    def test_models_are_frozen_and_decimal_exact(self) -> None:
        event = parse_binance_delta(delta(101, 101, [["100.10", "0.30"]]), 7)
        self.assertEqual(event.bids[0].price, Decimal("100.10"))
        self.assertEqual(event.bids[0].quantity, Decimal("0.30"))
        with self.assertRaises(FrozenInstanceError):
            event.final_update_id = 102  # type: ignore[misc]

    def test_rejects_malformed_ranges_and_levels(self) -> None:
        with self.assertRaises(SchemaError):
            parse_binance_delta(delta(102, 101), 1)
        with self.assertRaises(SchemaError):
            parse_binance_delta(delta(101, 101, [["100", "-1"]]), 1)
        bad = snapshot()
        bad["bids"].append(["100.0", "1"])
        with self.assertRaises(SchemaError):
            parse_binance_snapshot(bad, "BTCUSDT", 1)

    def test_combined_stream_envelope_is_supported(self) -> None:
        event = parse_binance_delta({"stream": "btcusdt@depth", "data": delta(101, 102)}, 1)
        self.assertEqual((event.first_update_id, event.final_update_id), (101, 102))

    def test_trade_schema_is_exact_and_exposes_aggressor_side(self) -> None:
        event = parse_binance_trade(
            {"stream": "btcusdt@trade", "data": trade(7, buyer_is_maker=True)}, 9
        )
        self.assertEqual(event.trade_id, 7)
        self.assertEqual(event.price, Decimal("100.2500"))
        self.assertEqual(event.quantity, Decimal("0.0300"))
        self.assertEqual(event.aggressor_side, "sell")

        first_possible_id = parse_binance_trade(trade(0), 9)
        self.assertEqual(first_possible_id.trade_id, 0)

    def test_trade_schema_rejects_invalid_values(self) -> None:
        invalid = trade(7)
        invalid["m"] = 1
        with self.assertRaises(SchemaError):
            parse_binance_trade(invalid, 1)
        invalid = trade(7)
        invalid["q"] = "0"
        with self.assertRaises(SchemaError):
            parse_binance_trade(invalid, 1)


class L2SequenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.book = L2Book("binance_spot", "BTCUSDT")
        self.book.load_snapshot(parse_binance_snapshot(snapshot(), "BTCUSDT", 1))

    def test_stale_bridge_and_delete(self) -> None:
        stale = parse_binance_delta(delta(90, 100), 2)
        self.assertIs(self.book.apply_delta(stale), ApplyStatus.STALE)
        bridge = parse_binance_delta(
            delta(99, 102, bids=[["100.00", "0"], ["100.50", "1.25"]]), 3
        )
        self.assertIs(self.book.apply_delta(bridge), ApplyStatus.APPLIED)
        self.assertNotIn(Decimal("100"), self.book.bids)
        self.assertEqual(self.book.best_bid, Decimal("100.50"))
        self.assertEqual(self.book.last_update_id, 102)

    def test_gap_invalidates_until_new_snapshot(self) -> None:
        gap = parse_binance_delta(delta(103, 103), 2)
        self.assertIs(self.book.apply_delta(gap), ApplyStatus.GAP)
        self.assertFalse(self.book.synchronized)
        next_event = parse_binance_delta(delta(101, 102), 3)
        self.assertIs(self.book.apply_delta(next_event), ApplyStatus.NEED_SNAPSHOT)

    def test_crossed_delta_is_atomic(self) -> None:
        digest = self.book.state_digest()
        crossed = parse_binance_delta(delta(101, 101, bids=[["101", "1"]]), 2)
        with self.assertRaises(SchemaError):
            self.book.apply_delta(crossed)
        self.assertEqual(self.book.state_digest(), digest)


class CaptureReplayTests(unittest.TestCase):
    def _write_capture(self, root: Path) -> Path:
        path = root / "btc.jsonl"
        with CaptureWriter(path, {"venue": "binance_spot", "symbol": "BTCUSDT"}) as writer:
            writer.write("snapshot", snapshot(), 1)
            writer.write("delta", delta(101, 101, asks=[["101", "2"]]), 2)
            writer.write("delta", delta(103, 103), 3)
            writer.write("gap", {"reason": "sequence_gap"}, 4)
            writer.write("snapshot", snapshot(103), 5)
            writer.write("delta", delta(104, 104, bids=[["100", "1.5"]]), 6)
        return path

    def test_manifest_and_replay_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_capture(Path(directory))
            manifest = verify_capture(path)
            self.assertEqual(manifest["record_count"], 7)
            self.assertEqual(manifest["metadata"]["symbol"], "BTCUSDT")
            first = replay_capture(path)
            second = replay_capture(path)
            self.assertEqual(first.book.state_digest(), second.book.state_digest())
            self.assertEqual((first.snapshots, first.applied_deltas, first.gaps), (2, 2, 1))
            self.assertTrue(first.book.synchronized)

    def test_capture_cannot_be_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_capture(Path(directory))
            with self.assertRaises(FileExistsError):
                CaptureWriter(path, {"venue": "binance_spot", "symbol": "BTCUSDT"})

    def test_replay_validates_trade_ids_within_snapshot_segments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.jsonl"
            with CaptureWriter(
                path, {"venue": "binance_spot", "symbol": "BTCUSDT"}
            ) as writer:
                writer.write("snapshot", snapshot(), 1)
                writer.write("trade", trade(10), 2)
                writer.write("trade_gap", {"after_trade_id": 10, "before_trade_id": 12}, 3)
                writer.write("trade", trade(12), 3)
                writer.write("trade", trade(12), 4)
                writer.write("trade", trade(11), 5)
                writer.write("snapshot", snapshot(), 6)
                writer.write("trade", trade(20), 7)

            summary = replay_capture(path)
            self.assertEqual(summary.accepted_trades, 3)
            self.assertEqual(summary.trade_id_gaps, 1)
            self.assertEqual(summary.duplicate_trades, 1)
            self.assertEqual(summary.out_of_order_trades, 1)

    def test_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_capture(Path(directory))
            records = path.read_text(encoding="utf-8").splitlines()
            record = json.loads(records[-1])
            record["payload"]["u"] = 999
            records[-1] = json.dumps(record)
            path.write_text("\n".join(records) + "\n", encoding="utf-8")
            with self.assertRaises(CaptureIntegrityError):
                verify_capture(path)


if __name__ == "__main__":
    unittest.main()
