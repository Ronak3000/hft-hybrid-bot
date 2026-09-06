from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.market_data import CaptureWriter, L2Book, parse_binance_snapshot
from scripts.capture_binance_l2 import (
    _ConnectionStats,
    _decode_stream_message,
    _record_stream_event,
)


class RealtimeCaptureTests(unittest.TestCase):
    def test_combined_envelope_is_decoded_without_losing_wrapper(self) -> None:
        raw = json.dumps(
            {"stream": "btcusdt@trade", "data": {"e": "trade", "t": 1}}
        )
        self.assertEqual(_decode_stream_message(raw)["stream"], "btcusdt@trade")

    def test_mixed_websocket_arrival_order_is_written(self) -> None:
        snapshot = {
            "lastUpdateId": 100,
            "bids": [["100", "1"]],
            "asks": [["102", "1"]],
        }
        trade = {
            "stream": "btcusdt@trade",
            "data": {
                "e": "trade",
                "E": 10,
                "s": "BTCUSDT",
                "t": 50,
                "p": "101",
                "q": "0.1",
                "T": 9,
                "m": False,
            },
        }
        depth = {
            "stream": "btcusdt@depth@100ms",
            "data": {
                "e": "depthUpdate",
                "E": 11,
                "s": "BTCUSDT",
                "U": 101,
                "u": 101,
                "b": [["100", "2"]],
                "a": [],
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            book = L2Book("binance_spot", "BTCUSDT")
            book.load_snapshot(parse_binance_snapshot(snapshot, "BTCUSDT", 1))
            stats = _ConnectionStats()
            with CaptureWriter(
                path, {"venue": "binance_spot", "symbol": "BTCUSDT"}
            ) as writer:
                writer.write("snapshot", snapshot, 1)
                _record_stream_event(trade, 2, writer, book, stats)
                _record_stream_event(depth, 3, writer, book, stats)
            kinds = [json.loads(line)["kind"] for line in path.read_text().splitlines()]

        self.assertEqual(kinds, ["metadata", "snapshot", "trade", "delta"])
        self.assertEqual(stats.accepted_trades, 1)
        self.assertEqual(stats.depth_events, 1)


if __name__ == "__main__":
    unittest.main()
