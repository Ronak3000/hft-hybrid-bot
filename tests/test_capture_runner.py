from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

from engine.market_data import CaptureWriter, L2Book, parse_binance_snapshot
from engine.research import (
    calibrate_avellaneda_stoikov,
    load_calibration,
    write_calibration,
)
from engine.simulation import (
    AvellanedaStoikovPolicy,
    CapturePolicyRunner,
    FixedSpreadPolicy,
    InventorySkewPolicy,
    SeededRandomPolicy,
    SimulationConfig,
)
from scripts.evaluate_capture_baselines import evaluate_baselines
from scripts.evaluate_sessions import evaluate_sessions
from scripts.run_sensitivity_grid import run_sensitivity_grid


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


def _calibration_capture(path: Path) -> None:
    with CaptureWriter(path, {"venue": "binance_spot", "symbol": "BTCUSDT"}) as writer:
        writer.write("snapshot", _snapshot(), 100)
        payload, received = _delta(101, 1_000_000_000, bids=[["101", "5"]])
        writer.write("delta", payload, received)
        prices = ["101", "101", "100.5", "100.5", "99.5"]
        for trade_id, price in enumerate(prices, start=1):
            received = 1_000_000_000 + trade_id * 100_000_000
            writer.write(
                "trade", _trade(trade_id, received, price=price, quantity="1"), received
            )
        payload, received = _delta(
            102, 2_000_000_000, asks=[["102", "0"], ["103", "5"]]
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

    def test_seeded_random_policy_is_repeatable(self) -> None:
        first = SeededRandomPolicy(Decimal("0.5"), Decimal("1"), seed=7)
        second = SeededRandomPolicy(Decimal("0.5"), Decimal("1"), seed=7)
        first_quotes = [first.quote(self.book, Decimal("0"), time) for time in range(10)]
        second_quotes = [
            second.quote(self.book, Decimal("0"), time) for time in range(10)
        ]
        self.assertEqual(first_quotes, second_quotes)
        self.assertGreater(len(set(first_quotes)), 1)

    def test_avellaneda_stoikov_inventory_and_horizon_behavior(self) -> None:
        flat = AvellanedaStoikovPolicy(
            tick_size=Decimal("0.01"),
            quantity=Decimal("1"),
            risk_aversion=Decimal("0.1"),
            volatility=Decimal("2"),
            intensity_decay=Decimal("1.5"),
            session_horizon_seconds=Decimal("1"),
        )
        long = AvellanedaStoikovPolicy(
            tick_size=Decimal("0.01"),
            quantity=Decimal("1"),
            risk_aversion=Decimal("0.1"),
            volatility=Decimal("2"),
            intensity_decay=Decimal("1.5"),
            session_horizon_seconds=Decimal("1"),
        )
        flat_quote = flat.quote(self.book, Decimal("0"), 1_000_000_000)
        long_quote = long.quote(self.book, Decimal("1"), 1_000_000_000)
        self.assertLess(long_quote.bid_price, flat_quote.bid_price)  # type: ignore[arg-type]
        self.assertLess(long_quote.ask_price, flat_quote.ask_price)  # type: ignore[arg-type]

        terminal = long.quote(self.book, Decimal("1"), 2_000_000_000)
        terminal_flat = flat.quote(self.book, Decimal("0"), 2_000_000_000)
        self.assertEqual(terminal, terminal_flat)
        with self.assertRaises(ValueError):
            long.quote(self.book, Decimal("0"), 1_500_000_000)

    def test_policy_configuration_validation(self) -> None:
        with self.assertRaises(ValueError):
            SeededRandomPolicy(
                Decimal("1"),
                Decimal("1"),
                seed=1,
                minimum_half_spread_ticks=3,
                maximum_half_spread_ticks=2,
            )
        with self.assertRaises(ValueError):
            AvellanedaStoikovPolicy(
                Decimal("1"),
                Decimal("1"),
                risk_aversion=Decimal("0"),
                volatility=Decimal("1"),
                intensity_decay=Decimal("1"),
                session_horizon_seconds=Decimal("1"),
            )

    def test_avellaneda_stoikov_ignores_global_decimal_precision(self) -> None:
        def quote(precision: int):
            with localcontext() as context:
                context.prec = precision
                policy = AvellanedaStoikovPolicy(
                    Decimal("0.01"),
                    Decimal("0.1"),
                    risk_aversion=Decimal("0.00123456789"),
                    volatility=Decimal("0.56789"),
                    intensity_decay=Decimal("1.2345"),
                    session_horizon_seconds=Decimal("60"),
                )
                return policy.quote(self.book, Decimal("0.25"), 1)

        self.assertEqual(quote(6), quote(28))


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
        self.assertEqual(
            set(first["policies"]),
            {
                "fixed_spread",
                "inventory_skew",
                "seeded_random",
                "avellaneda_stoikov",
            },
        )

    def test_sensitivity_grid_is_bounded_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            arguments = {
                "fee_rates": (Decimal("0"), Decimal("0.001")),
                "order_latencies_ns": (0,),
                "half_spread_ticks": (1,),
                "tick_size": Decimal("0.5"),
                "quantity": Decimal("1"),
                "max_skew_ticks": Decimal("2"),
                "initial_cash": Decimal("1000"),
                "cancel_latency_ns": 0,
                "max_abs_inventory": Decimal("10"),
                "markout_horizons_ns": (2,),
                "random_seed": 7,
                "as_risk_aversion": Decimal("0.001"),
                "as_volatility": Decimal("0.5"),
                "as_intensity_decay": Decimal("1"),
                "as_session_horizon_seconds": Decimal("60"),
            }
            first = run_sensitivity_grid(path, **arguments)
            second = run_sensitivity_grid(path, **arguments)
            with self.assertRaises(ValueError):
                run_sensitivity_grid(path, max_scenarios=1, **arguments)

        self.assertEqual(first, second)
        self.assertEqual(first["scenario_count"], 2)


class CalibrationTests(unittest.TestCase):
    def test_training_capture_calibration_is_source_linked_and_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "training.jsonl"
            _calibration_capture(capture)
            with localcontext() as context:
                context.prec = 6
                first = calibrate_avellaneda_stoikov(
                    [capture], [Decimal("0.5"), Decimal("1"), Decimal("2")]
                )
            second = calibrate_avellaneda_stoikov(
                [capture], [Decimal("0.5"), Decimal("1"), Decimal("2")]
            )
            output = root / "calibration.json"
            write_calibration(first, output)
            loaded = load_calibration(output)

        self.assertEqual(first.report(), second.report())
        self.assertEqual(
            [item.reached_trades for item in first.distance_intensities], [5, 3, 1]
        )
        self.assertGreater(first.volatility_per_sqrt_second, 0)
        self.assertGreater(first.intensity_decay, 0)
        self.assertGreaterEqual(first.intensity_fit_r_squared, 0)
        self.assertLessEqual(first.intensity_fit_r_squared, 1)
        self.assertEqual(loaded["source_captures"][0]["capture_file"], "training.jsonl")

    def test_calibration_rejects_duplicate_sources_and_too_few_bins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "training.jsonl"
            _calibration_capture(capture)
            with self.assertRaises(ValueError):
                calibrate_avellaneda_stoikov([capture, capture], ["0.5", "1"])
            with self.assertRaises(ValueError):
                calibrate_avellaneda_stoikov([capture], ["0.5"])

    def test_frozen_calibration_evaluation_is_paired_and_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            training = root / "training.jsonl"
            first_session = root / "session-one.jsonl"
            second_session = root / "session-two.jsonl"
            calibration_path = root / "calibration.json"
            _calibration_capture(training)
            _capture(first_session)
            _capture(second_session, with_gap=True)
            calibration = calibrate_avellaneda_stoikov(
                [training], [Decimal("0.5"), Decimal("1"), Decimal("2")]
            )
            write_calibration(calibration, calibration_path)
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
                "random_seed": 7,
                "as_risk_aversion": Decimal("0.001"),
                "as_session_horizon_seconds": Decimal("60"),
                "bootstrap_seed": 17,
                "bootstrap_samples": 100,
            }
            first = evaluate_sessions(
                calibration_path, (first_session, second_session), **arguments
            )
            second = evaluate_sessions(
                calibration_path, (first_session, second_session), **arguments
            )

        self.assertEqual(first, second)
        self.assertEqual(first["session_count"], 2)
        self.assertEqual(first["evaluation_configuration"]["tick_size"], "0.5")
        self.assertEqual(first["sessions"][0]["capture_metadata"]["symbol"], "BTCUSDT")
        self.assertEqual(
            set(first["paired_net_pnl_differences"]),
            {
                "inventory_skew_minus_fixed_spread",
                "seeded_random_minus_fixed_spread",
                "avellaneda_stoikov_minus_fixed_spread",
            },
        )
        self.assertEqual(
            first["policy_net_pnl_summary"]["fixed_spread"]["sessions"], 2
        )

    def test_session_evaluation_rejects_training_overlap_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            training = root / "training.jsonl"
            first_session = root / "session-one.jsonl"
            second_session = root / "session-two.jsonl"
            calibration_path = root / "calibration.json"
            _calibration_capture(training)
            _capture(first_session)
            _capture(second_session, with_gap=True)
            calibration = calibrate_avellaneda_stoikov(
                [training], [Decimal("0.5"), Decimal("1"), Decimal("2")]
            )
            write_calibration(calibration, calibration_path)
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
                "random_seed": 7,
                "as_risk_aversion": Decimal("0.001"),
                "as_session_horizon_seconds": Decimal("60"),
                "bootstrap_samples": 10,
            }
            with self.assertRaisesRegex(ValueError, "overlaps calibration"):
                evaluate_sessions(
                    calibration_path, (training, first_session), **arguments
                )
            with self.assertRaisesRegex(ValueError, "duplicate evaluation"):
                evaluate_sessions(
                    calibration_path, (first_session, first_session), **arguments
                )


if __name__ == "__main__":
    unittest.main()
