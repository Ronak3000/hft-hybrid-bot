from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from engine.market_data import CaptureWriter, L2Book, parse_binance_snapshot
from engine.simulation import (
    CapturePolicyRunner,
    FixedSpreadPolicy,
    InventorySkewPolicy,
    SimulationConfig,
)
from scripts.evaluate_capture_baselines import evaluate_baselines


def _snapshot() -> dict:
    return {
        "lastUpdateId": 100,
        "bids": [["100", "5"]],
        "asks": [["102", "5"]],
    }


def _delta(update_id: int, received: int, bids=None, asks=None) -> tuple[dict, int]:
    return (
        {
            "e": "depthUpdate",
            "E": received // 1_000_000,
            "s": "BTCUSDT",
            "U": update_id,
            "u": update_id,
            "b": bids or [],
            "a": asks or [],
        },
        received,
    )


def _trade(trade_id: int, received: int, price="101", quantity="6") -> dict:
    return {
        "e": "trade",
        "E": received // 1_000_000,
        "s": "BTCUSDT",
        "t": trade_id,
        "p": price,
        "q": quantity,
        "T": received // 1_000_000,
        "m": True,
    }


def _capture(path: Path, *, with_gap: bool = False) -> None:
    with CaptureWriter(path, {"venue": "binance_spot", "symbol": "BTCUSDT"}) as writer:
        # The snapshot HTTP response arrived at t=10. The first delta was
        # buffered from t=5 and must reconstruct the book without being traded.
        writer.write("snapshot", _snapshot(), 10)
        payload, received = _delta(101, 5, bids=[["101", "5"]])
        writer.write("delta", payload, received)
        payload, received = _delta(102, 12)
        writer.write("delta", payload, received)
        if with_gap:
            writer.write(
                "trade_gap",
                {"after_trade_id": 1, "before_trade_id": 3},
                13,
            )
        writer.write("trade", _trade(1, 13), 13)
        payload, received = _delta(
            103, 15, bids=[["101", "0"], ["100", "5"]]
        )
        writer.write("delta", payload, received)


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.book = L2Book("binance_spot", "BTCUSDT")
        self.book.load_snapshot(parse_binance_snapshot(_snapshot(), "BTCUSDT", 1))

    def test_fixed_spread_is_tick_aligned(self) -> None:
        policy = FixedSpreadPolicy(Decimal("0.5"), Decimal("1"), 1)
        target = policy.quote(self.book, Decimal("0"))
        self.assertEqual(target.bid_price, Decimal("100.5"))
        self.assertEqual(target.ask_price, Decimal("101.5"))

    def test_positive_inventory_moves_both_quotes_lower(self) -> None:
        policy = InventorySkewPolicy(
            tick_size=Decimal("0.5"),
            quantity=Decimal("1"),
            half_spread_ticks=1,
            max_abs_inventory=Decimal("10"),
            max_skew_ticks=Decimal("2"),
        )
        flat = policy.quote(self.book, Decimal("0"))
        long = policy.quote(self.book, Decimal("10"))
        self.assertLess(long.bid_price, flat.bid_price)  # type: ignore[arg-type]
        self.assertLess(long.ask_price, flat.ask_price)  # type: ignore[arg-type]


class CapturePolicyRunnerTests(unittest.TestCase):
    def test_buffered_events_are_warmup_and_real_trade_fills_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            runner = CapturePolicyRunner(
                FixedSpreadPolicy(Decimal("0.5"), Decimal("1"), 1),
                SimulationConfig(initial_cash=Decimal("1000")),
                markout_horizons_ns=(2,),
            )
            result = runner.run(path)
            with self.assertRaises(RuntimeError):
                runner.run(path)

        metrics = result.metrics
        self.assertEqual(metrics.snapshots, 1)
        self.assertEqual(metrics.applied_deltas, 3)
        self.assertEqual(metrics.public_trades, 1)
        self.assertEqual(metrics.warmup_trades, 0)
        self.assertEqual(metrics.fills, 1)
        self.assertEqual(metrics.filled_quantity, Decimal("1"))
        self.assertEqual(metrics.maximum_absolute_inventory, Decimal("1"))
        self.assertEqual(metrics.open_orders_at_end, 0)
        self.assertEqual(metrics.turnover, Decimal("101.0"))
        self.assertEqual(metrics.net_pnl, Decimal("0.0"))
        self.assertEqual(result.attributions[0].spread_edge, Decimal("0.5"))
        self.assertEqual(result.attributions[0].signed_markouts[2], Decimal("0.0"))

    def test_trade_gap_disables_fills_until_a_fresh_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path, with_gap=True)
            result = CapturePolicyRunner(
                FixedSpreadPolicy(Decimal("0.5"), Decimal("1"), 1)
            ).run(path)

        self.assertEqual(result.metrics.fills, 0)
        self.assertEqual(result.metrics.warmup_trades, 1)
        self.assertGreater(result.metrics.invalidated_orders, 0)

    def test_runner_rejects_duplicate_markout_horizons(self) -> None:
        policy = FixedSpreadPolicy(Decimal("1"), Decimal("1"))
        with self.assertRaises(ValueError):
            CapturePolicyRunner(policy, markout_horizons_ns=(10, 10))

    def test_baseline_report_is_reproducible_and_source_linked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            arguments = {
                "tick_size": Decimal("0.5"),
                "quantity": Decimal("1"),
                "half_spread_ticks": 1,
                "max_skew_ticks": Decimal("2"),
                "initial_cash": Decimal("1000"),
                "maker_fee_rate": Decimal("0"),
                "order_latency_ns": 0,
                "cancel_latency_ns": 0,
                "max_abs_inventory": Decimal("10"),
                "markout_horizons_ns": (2,),
            }
            first = evaluate_baselines(path, **arguments)
            second = evaluate_baselines(path, **arguments)

        self.assertEqual(first, second)
        self.assertEqual(first["source_capture"], "capture.jsonl")
        self.assertEqual(first["policies"]["fixed_spread"]["metrics"]["fills"], 1)


if __name__ == "__main__":
    unittest.main()
