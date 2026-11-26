"""Calibrate the chance of at least one simulated fill by a fixed horizon."""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.research.fill_probability import evaluate_fill_probabilities
from engine.research.trade_hawkes import load_arrivals
from engine.simulation import SimulationConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("train", "validation", "test"):
        parser.add_argument(f"--{name}", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--horizon-ms", type=int, default=1000)
    parser.add_argument("--stride", type=int, default=10)
    parser.add_argument("--offsets", nargs="+", type=int, default=(0, 4, 64, 256))
    parser.add_argument("--sizes", nargs="+", type=Decimal,
                        default=(Decimal("0.00025"), Decimal("0.0005"), Decimal("0.001")))
    parser.add_argument("--tick-size", type=Decimal, default=Decimal("0.01"))
    parser.add_argument("--latency-ns", type=int, default=1_000_000)
    args = parser.parse_args()
    if (min(args.horizon_ms, args.stride) < 1 or args.latency_ns < 0
            or min(args.offsets) < 0 or len(set(args.offsets)) != len(args.offsets)
            or len(set(args.sizes)) != len(args.sizes)
            or any(not size.is_finite() or size <= 0 for size in [args.tick_size, *args.sizes])):
        parser.error("invalid probe horizon, stride, offsets, size or latency")
    if args.output.exists():
        parser.error("use a new output path")
    try:
        splits = {name: [load_arrivals(path) for path in getattr(args, name)]
                  for name in ("train", "validation", "test")}
        config = SimulationConfig(order_latency_ns=args.latency_ns,
                                  max_abs_inventory=max(args.sizes))
        report = evaluate_fill_probabilities(
            splits, config=config, tick_size=args.tick_size, quantities=tuple(args.sizes),
            horizon_ns=args.horizon_ms * 1_000_000, stride=args.stride, offsets=tuple(args.offsets),
        )
        report["settings"] = {"horizon_ms": args.horizon_ms, "stride": args.stride,
                              "offsets": args.offsets, "sizes": args.sizes, "tick_size": args.tick_size,
                              "latency_ns": args.latency_ns}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, default=str, allow_nan=False)
            output.write("\n")
    except (OSError, ValueError, ArithmeticError) as exc:
        parser.error(str(exc))
    print(f"Fill probability report: {args.output}")


if __name__ == "__main__":
    main()
