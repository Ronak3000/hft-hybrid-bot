"""Evaluate frozen baselines across out-of-sample capture sessions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.market_data import verify_capture
from engine.research import load_calibration
from engine.simulation.queue_simulator import SIMULATION_DECIMAL_CONTEXT
from scripts.evaluate_capture_baselines import evaluate_baselines


SESSION_EVALUATION_SCHEMA_VERSION = 1


def evaluate_sessions(
    calibration_path: str | Path,
    session_paths: tuple[str | Path, ...],
    *,
    tick_size: Decimal,
    quantity: Decimal,
    half_spread_ticks: int,
    max_skew_ticks: Decimal,
    initial_cash: Decimal,
    maker_fee_rate: Decimal,
    order_latency_ns: int,
    cancel_latency_ns: int,
    max_abs_inventory: Decimal,
    markout_horizons_ns: tuple[int, ...],
    random_seed: int,
    as_risk_aversion: Decimal,
    as_session_horizon_seconds: Decimal,
    bootstrap_seed: int = 17,
    bootstrap_samples: int = 2000,
) -> dict[str, Any]:
    if len(session_paths) < 2:
        raise ValueError("at least two out-of-sample sessions are required")
    if isinstance(bootstrap_samples, bool) or bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    calibration = load_calibration(calibration_path)
    training_hashes = {
        source["sha256"] for source in calibration["source_captures"]
    }
    sessions: list[dict[str, Any]] = []
    evaluation_hashes: set[str] = set()
    for path_value in session_paths:
        path = Path(path_value)
        manifest = verify_capture(path)
        capture_hash = manifest["sha256"]
        if capture_hash in training_hashes:
            raise ValueError(
                f"evaluation capture overlaps calibration data: {path.name}"
            )
        if capture_hash in evaluation_hashes:
            raise ValueError(f"duplicate evaluation capture content: {path.name}")
        evaluation_hashes.add(capture_hash)
        result = evaluate_baselines(
            path,
            tick_size=tick_size,
            quantity=quantity,
            half_spread_ticks=half_spread_ticks,
            max_skew_ticks=max_skew_ticks,
            initial_cash=initial_cash,
            maker_fee_rate=maker_fee_rate,
            order_latency_ns=order_latency_ns,
            cancel_latency_ns=cancel_latency_ns,
            max_abs_inventory=max_abs_inventory,
            markout_horizons_ns=markout_horizons_ns,
            random_seed=random_seed,
            as_risk_aversion=as_risk_aversion,
            as_volatility=Decimal(calibration["volatility_per_sqrt_second"]),
            as_intensity_decay=Decimal(calibration["intensity_decay"]),
            as_session_horizon_seconds=as_session_horizon_seconds,
        )
        sessions.append(
            {
                "capture_file": path.name,
                "capture_sha256": capture_hash,
                "capture_metadata": result["capture_metadata"],
                "policies": result["policies"],
            }
        )

    policy_names = tuple(sessions[0]["policies"])
    aggregates: dict[str, Any] = {}
    for index, policy_name in enumerate(policy_names):
        net_values = tuple(
            Decimal(session["policies"][policy_name]["metrics"]["net_pnl"])
            for session in sessions
        )
        aggregate = _distribution_summary(
            net_values, bootstrap_seed + index, bootstrap_samples
        )
        aggregate["mean_fills"] = str(
            _mean(
                tuple(
                    Decimal(session["policies"][policy_name]["metrics"]["fills"])
                    for session in sessions
                )
            )
        )
        aggregate["mean_turnover"] = str(
            _mean(
                tuple(
                    Decimal(
                        session["policies"][policy_name]["metrics"]["turnover"]
                    )
                    for session in sessions
                )
            )
        )
        aggregates[policy_name] = aggregate

    paired: dict[str, Any] = {}
    fixed_values = tuple(
        Decimal(session["policies"]["fixed_spread"]["metrics"]["net_pnl"])
        for session in sessions
    )
    for index, policy_name in enumerate(policy_names):
        if policy_name == "fixed_spread":
            continue
        differences = tuple(
            Decimal(session["policies"][policy_name]["metrics"]["net_pnl"])
            - fixed
            for session, fixed in zip(sessions, fixed_values)
        )
        paired[f"{policy_name}_minus_fixed_spread"] = _distribution_summary(
            differences, bootstrap_seed + 100 + index, bootstrap_samples
        )

    calibration_bytes = Path(calibration_path).read_bytes()
    return {
        "session_evaluation_schema_version": SESSION_EVALUATION_SCHEMA_VERSION,
        "calibration_file": Path(calibration_path).name,
        "calibration_sha256": hashlib.sha256(calibration_bytes).hexdigest(),
        "calibration_parameters": {
            "volatility_per_sqrt_second": calibration[
                "volatility_per_sqrt_second"
            ],
            "intensity_decay": calibration["intensity_decay"],
            "intensity_scale_per_second": calibration[
                "intensity_scale_per_second"
            ],
            "intensity_fit_r_squared": calibration[
                "intensity_fit_r_squared"
            ],
        },
        "bootstrap": {
            "seed": bootstrap_seed,
            "samples": bootstrap_samples,
            "interval": "percentile_95_percent_session_resampling",
        },
        "evaluation_configuration": result["configuration"],
        "session_count": len(sessions),
        "sessions": sessions,
        "policy_net_pnl_summary": aggregates,
        "paired_net_pnl_differences": paired,
    }


def _distribution_summary(
    values: tuple[Decimal, ...], seed: int, samples: int
) -> dict[str, Any]:
    mean = _mean(values)
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        sample_variance = sum(
            ((value - mean) ** 2 for value in values), Decimal("0")
        ) / Decimal(len(values) - 1)
        sample_standard_deviation = sample_variance.sqrt()
    random = _SplitMix64(seed)
    bootstrap_means: list[Decimal] = []
    for _ in range(samples):
        resample = tuple(values[random.next_u64() % len(values)] for _ in values)
        bootstrap_means.append(_mean(resample))
    bootstrap_means.sort()
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        last = Decimal(samples - 1)
        lower_index = int(
            (Decimal("0.025") * last).to_integral_value(rounding=ROUND_FLOOR)
        )
        upper_index = int(
            (Decimal("0.975") * last).to_integral_value(rounding=ROUND_CEILING)
        )
    return {
        "sessions": len(values),
        "mean": str(mean),
        "sample_standard_deviation": str(sample_standard_deviation),
        "bootstrap_95_percent_lower": str(bootstrap_means[lower_index]),
        "bootstrap_95_percent_upper": str(bootstrap_means[upper_index]),
    }


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        return sum(values, Decimal("0")) / Decimal(len(values))


class _SplitMix64:
    def __init__(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("bootstrap seed must be an integer")
        self.state = seed & ((1 << 64) - 1)

    def next_u64(self) -> int:
        mask = (1 << 64) - 1
        self.state = (self.state + 0x9E3779B97F4A7C15) & mask
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & mask
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & mask
        return (value ^ (value >> 31)) & mask


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--sessions", type=Path, nargs="+", required=True)
    parser.add_argument("--tick-size", type=Decimal, required=True)
    parser.add_argument("--quantity", type=Decimal, required=True)
    parser.add_argument("--half-spread-ticks", type=int, default=1)
    parser.add_argument("--max-skew-ticks", type=Decimal, default=Decimal("2"))
    parser.add_argument("--initial-cash", type=Decimal, default=Decimal("1000000"))
    parser.add_argument("--maker-fee-rate", type=Decimal, default=Decimal("0"))
    parser.add_argument("--order-latency-ns", type=int, default=0)
    parser.add_argument("--cancel-latency-ns", type=int, default=0)
    parser.add_argument("--max-abs-inventory", type=Decimal, default=Decimal("1"))
    parser.add_argument("--markout-ms", type=int, nargs="*", default=[100, 1000])
    parser.add_argument("--random-seed", type=int, default=7)
    parser.add_argument("--as-risk-aversion", type=Decimal, default=Decimal("0.001"))
    parser.add_argument(
        "--as-session-horizon-seconds", type=Decimal, default=Decimal("60")
    )
    parser.add_argument("--bootstrap-seed", type=int, default=17)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_sessions(
        args.calibration,
        tuple(args.sessions),
        tick_size=args.tick_size,
        quantity=args.quantity,
        half_spread_ticks=args.half_spread_ticks,
        max_skew_ticks=args.max_skew_ticks,
        initial_cash=args.initial_cash,
        maker_fee_rate=args.maker_fee_rate,
        order_latency_ns=args.order_latency_ns,
        cancel_latency_ns=args.cancel_latency_ns,
        max_abs_inventory=args.max_abs_inventory,
        markout_horizons_ns=tuple(value * 1_000_000 for value in args.markout_ms),
        random_seed=args.random_seed,
        as_risk_aversion=args.as_risk_aversion,
        as_session_horizon_seconds=args.as_session_horizon_seconds,
        bootstrap_seed=args.bootstrap_seed,
        bootstrap_samples=args.bootstrap_samples,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Evaluation sessions: {report['session_count']}")
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
