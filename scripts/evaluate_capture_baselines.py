"""Evaluate deterministic market-making baselines on one verified capture."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.market_data import verify_capture
from engine.simulation import (
    CapturePolicyRunner,
    FixedSpreadPolicy,
    InventorySkewPolicy,
    SimulationConfig,
)
from engine.simulation.queue_simulator import SIMULATION_DECIMAL_CONTEXT


REPORT_SCHEMA_VERSION = 1


def evaluate_baselines(
    capture_path: str | Path,
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
) -> dict[str, Any]:
    source = verify_capture(capture_path)
    config = SimulationConfig(
        initial_cash=initial_cash,
        maker_fee_rate=maker_fee_rate,
        order_latency_ns=order_latency_ns,
        cancel_latency_ns=cancel_latency_ns,
        max_abs_inventory=max_abs_inventory,
    )
    policies = {
        "fixed_spread": FixedSpreadPolicy(
            tick_size=tick_size,
            quantity=quantity,
            half_spread_ticks=half_spread_ticks,
        ),
        "inventory_skew": InventorySkewPolicy(
            tick_size=tick_size,
            quantity=quantity,
            half_spread_ticks=half_spread_ticks,
            max_abs_inventory=max_abs_inventory,
            max_skew_ticks=max_skew_ticks,
        ),
    }
    results: dict[str, Any] = {}
    for name, policy in policies.items():
        run = CapturePolicyRunner(
            policy, config, markout_horizons_ns=markout_horizons_ns
        ).run(capture_path)
        results[name] = {
            "metrics": _jsonable(run.metrics),
            "attribution": _attribution_summary(
                run.attributions, markout_horizons_ns
            ),
            "final_book_digest": run.final_book_digest,
        }

    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "source_capture": Path(capture_path).name,
        "source_sha256": source["sha256"],
        "capture_metadata": source["metadata"],
        "configuration": {
            "tick_size": str(tick_size),
            "quantity": str(quantity),
            "half_spread_ticks": half_spread_ticks,
            "max_skew_ticks": str(max_skew_ticks),
            "initial_cash": str(config.initial_cash),
            "maker_fee_rate": str(config.maker_fee_rate),
            "order_latency_ns": config.order_latency_ns,
            "cancel_latency_ns": config.cancel_latency_ns,
            "max_abs_inventory": str(config.max_abs_inventory),
            "markout_horizons_ns": list(markout_horizons_ns),
        },
        "policies": results,
    }


def _attribution_summary(attributions: tuple[Any, ...], horizons: tuple[int, ...]) -> dict:
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        spread_edge = sum(
            (item.spread_edge for item in attributions), Decimal("0")
        )
    markouts: dict[str, Any] = {}
    for horizon in horizons:
        observed = [
            item.signed_markouts[horizon]
            for item in attributions
            if horizon in item.signed_markouts
        ]
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            total = sum(observed, Decimal("0"))
            mean = total / len(observed) if observed else None
            markouts[str(horizon)] = {
                "observed_fills": len(observed),
                "total_signed_markout": str(total),
                "mean_signed_markout": str(mean) if mean is not None else None,
            }
    return {
        "total_spread_edge_at_fill": str(spread_edge),
        "markouts_by_horizon_ns": markouts,
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--tick-size", type=Decimal, required=True)
    parser.add_argument("--quantity", type=Decimal, required=True)
    parser.add_argument("--half-spread-ticks", type=int, default=1)
    parser.add_argument("--max-skew-ticks", type=Decimal, default=Decimal("2"))
    parser.add_argument("--initial-cash", type=Decimal, default=Decimal("1000000"))
    parser.add_argument("--maker-fee-rate", type=Decimal, default=Decimal("0"))
    parser.add_argument("--order-latency-ns", type=int, default=0)
    parser.add_argument("--cancel-latency-ns", type=int, default=0)
    parser.add_argument("--max-abs-inventory", type=Decimal, default=Decimal("1"))
    parser.add_argument(
        "--markout-ms", type=int, nargs="*", default=[100, 1000, 5000]
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if any(horizon <= 0 for horizon in args.markout_ms):
        parser.error("--markout-ms values must be positive")
    horizons = tuple(horizon * 1_000_000 for horizon in args.markout_ms)
    report = evaluate_baselines(
        args.capture,
        tick_size=args.tick_size,
        quantity=args.quantity,
        half_spread_ticks=args.half_spread_ticks,
        max_skew_ticks=args.max_skew_ticks,
        initial_cash=args.initial_cash,
        maker_fee_rate=args.maker_fee_rate,
        order_latency_ns=args.order_latency_ns,
        cancel_latency_ns=args.cancel_latency_ns,
        max_abs_inventory=args.max_abs_inventory,
        markout_horizons_ns=horizons,
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as destination:
            destination.write(encoded)
        print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
