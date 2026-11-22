"""Compare plain, symmetrically widened, and signal-widened quotes on identical L2."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.research.alpha_quotes import evaluate_alpha_quotes
from engine.research.lob_alpha import load_session, validate_splits
from engine.simulation import AvellanedaStoikovPolicy, SimulationConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for split in ("train", "validation"):
        parser.add_argument(f"--{split}", nargs="+", type=Path, required=True)
    parser.add_argument("--test-capture", nargs="+", type=Path, required=True)
    parser.add_argument("--test-features", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--widen-ticks", type=int, default=1)
    parser.add_argument("--tick-size", type=Decimal, required=True)
    parser.add_argument("--quantity", type=Decimal, required=True)
    parser.add_argument("--maker-fee-rate", type=Decimal, required=True)
    parser.add_argument("--order-latency-ns", type=int, required=True)
    parser.add_argument("--cancel-latency-ns", type=int, required=True)
    parser.add_argument("--inventory-limit", type=Decimal, required=True)
    args = parser.parse_args()
    if len(args.test_capture) != len(args.test_features):
        parser.error("provide one feature file per test capture, in the same order")
    if args.output.exists():
        parser.error(f"report already exists: {args.output}")
    try:
        config = SimulationConfig(
            maker_fee_rate=args.maker_fee_rate, order_latency_ns=args.order_latency_ns,
            cancel_latency_ns=args.cancel_latency_ns, max_abs_inventory=args.inventory_limit,
        )
        policy_terms = {
            "tick_size": args.tick_size, "quantity": args.quantity,
            "risk_aversion": Decimal("0.001"), "volatility": Decimal("0.5"),
            "intensity_decay": Decimal("1"), "session_horizon_seconds": Decimal("60"),
        }
        train = [load_session(path) for path in args.train]
        validation = [load_session(path) for path in args.validation]
        validate_splits({
            "train": train, "validation": validation,
            "test": [load_session(path) for path in args.test_features],
        })
        sessions = []
        for capture, features in zip(args.test_capture, args.test_features, strict=True):
            result = evaluate_alpha_quotes(
                train, validation, capture, features, config=config,
                policy=AvellanedaStoikovPolicy(**policy_terms),
                horizon=args.horizon, widen_ticks=args.widen_ticks,
                markout_horizons_ns=(100_000_000, 1_000_000_000),
            )
            result["test_capture"] = capture.name
            result["net_pnl_difference"] = (
                result["alpha_widened"]["net_pnl"] - result["avellaneda_stoikov"]["net_pnl"]
            )
            result["net_pnl_difference_vs_symmetric"] = (
                result["alpha_widened"]["net_pnl"] - result["symmetric_widened"]["net_pnl"]
            )
            sessions.append(result)
        report = {
            "schema_version": 3,
            "policy_parameters": policy_terms,
            "simulation_parameters": asdict(config),
            "sessions": sessions,
            "mean_session_net_pnl_difference": (
                sum(item["net_pnl_difference"] for item in sessions) / len(sessions)
            ),
            "mean_session_net_pnl_difference_vs_symmetric": (
                sum(item["net_pnl_difference_vs_symmetric"] for item in sessions) / len(sessions)
            ),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(report, default=str, indent=2, allow_nan=False) + "\n")
    except (ValueError, OSError, ArithmeticError) as exc:
        parser.error(str(exc))
    print(f"Paired Avellaneda–Stoikov report: {args.output}")


if __name__ == "__main__":
    main()
