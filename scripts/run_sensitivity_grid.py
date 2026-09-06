"""Run bounded fee/latency/spread sensitivity grids on one capture."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_capture_baselines import evaluate_baselines


SENSITIVITY_SCHEMA_VERSION = 1


def run_sensitivity_grid(
    capture_path: str | Path,
    *,
    fee_rates: tuple[Decimal, ...],
    order_latencies_ns: tuple[int, ...],
    half_spread_ticks: tuple[int, ...],
    tick_size: Decimal,
    quantity: Decimal,
    max_skew_ticks: Decimal,
    initial_cash: Decimal,
    cancel_latency_ns: int,
    max_abs_inventory: Decimal,
    markout_horizons_ns: tuple[int, ...],
    random_seed: int,
    as_risk_aversion: Decimal,
    as_volatility: Decimal,
    as_intensity_decay: Decimal,
    as_session_horizon_seconds: Decimal,
    max_scenarios: int = 100,
) -> dict[str, Any]:
    dimensions = (fee_rates, order_latencies_ns, half_spread_ticks)
    if any(not values for values in dimensions):
        raise ValueError("sensitivity dimensions must not be empty")
    scenario_count = len(fee_rates) * len(order_latencies_ns) * len(half_spread_ticks)
    if isinstance(max_scenarios, bool) or max_scenarios <= 0:
        raise ValueError("max_scenarios must be positive")
    if scenario_count > max_scenarios:
        raise ValueError(
            f"grid has {scenario_count} scenarios; maximum is {max_scenarios}"
        )

    scenarios: list[dict[str, Any]] = []
    source_fields: dict[str, Any] | None = None
    for index, (fee, latency, spread) in enumerate(
        itertools.product(fee_rates, order_latencies_ns, half_spread_ticks), start=1
    ):
        evaluation = evaluate_baselines(
            capture_path,
            tick_size=tick_size,
            quantity=quantity,
            half_spread_ticks=spread,
            max_skew_ticks=max_skew_ticks,
            initial_cash=initial_cash,
            maker_fee_rate=fee,
            order_latency_ns=latency,
            cancel_latency_ns=cancel_latency_ns,
            max_abs_inventory=max_abs_inventory,
            markout_horizons_ns=markout_horizons_ns,
            random_seed=random_seed,
            as_risk_aversion=as_risk_aversion,
            as_volatility=as_volatility,
            as_intensity_decay=as_intensity_decay,
            as_session_horizon_seconds=as_session_horizon_seconds,
        )
        if source_fields is None:
            source_fields = {
                "source_capture": evaluation["source_capture"],
                "source_sha256": evaluation["source_sha256"],
                "capture_metadata": evaluation["capture_metadata"],
            }
        scenarios.append(
            {
                "scenario_id": index,
                "configuration": evaluation["configuration"],
                "policies": evaluation["policies"],
            }
        )
    assert source_fields is not None
    return {
        "sensitivity_schema_version": SENSITIVITY_SCHEMA_VERSION,
        **source_fields,
        "scenario_count": scenario_count,
        "scenarios": scenarios,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--tick-size", type=Decimal, required=True)
    parser.add_argument("--quantity", type=Decimal, required=True)
    parser.add_argument("--fee-rates", type=Decimal, nargs="+", required=True)
    parser.add_argument("--order-latencies-ns", type=int, nargs="+", required=True)
    parser.add_argument("--half-spread-ticks", type=int, nargs="+", required=True)
    parser.add_argument("--max-skew-ticks", type=Decimal, default=Decimal("2"))
    parser.add_argument("--initial-cash", type=Decimal, default=Decimal("1000000"))
    parser.add_argument("--cancel-latency-ns", type=int, default=0)
    parser.add_argument("--max-abs-inventory", type=Decimal, default=Decimal("1"))
    parser.add_argument("--markout-ms", type=int, nargs="*", default=[100, 1000])
    parser.add_argument("--random-seed", type=int, default=7)
    parser.add_argument("--as-risk-aversion", type=Decimal, default=Decimal("0.001"))
    parser.add_argument("--as-volatility", type=Decimal, default=Decimal("0.5"))
    parser.add_argument("--as-intensity-decay", type=Decimal, default=Decimal("1"))
    parser.add_argument(
        "--as-session-horizon-seconds", type=Decimal, default=Decimal("60")
    )
    parser.add_argument("--max-scenarios", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_sensitivity_grid(
        args.capture,
        fee_rates=tuple(args.fee_rates),
        order_latencies_ns=tuple(args.order_latencies_ns),
        half_spread_ticks=tuple(args.half_spread_ticks),
        tick_size=args.tick_size,
        quantity=args.quantity,
        max_skew_ticks=args.max_skew_ticks,
        initial_cash=args.initial_cash,
        cancel_latency_ns=args.cancel_latency_ns,
        max_abs_inventory=args.max_abs_inventory,
        markout_horizons_ns=tuple(value * 1_000_000 for value in args.markout_ms),
        random_seed=args.random_seed,
        as_risk_aversion=args.as_risk_aversion,
        as_volatility=args.as_volatility,
        as_intensity_decay=args.as_intensity_decay,
        as_session_horizon_seconds=args.as_session_horizon_seconds,
        max_scenarios=args.max_scenarios,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Scenarios: {report['scenario_count']}")
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
