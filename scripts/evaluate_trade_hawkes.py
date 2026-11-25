"""Fit a development Hawkes arrival baseline on real BTCUSDT trades."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.research.trade_hawkes import evaluate_arrivals, load_arrivals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("train", "validation", "test")
    for name in names:
        parser.add_argument(f"--{name}", nargs="+", type=Path, required=True)
    parser.add_argument("--decay", type=float, default=5.0)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a new output path")
    try:
        report = evaluate_arrivals(*[[load_arrivals(path) for path in getattr(args, name)]
                                     for name in names], decay=args.decay)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as destination:
            json.dump(report, destination, indent=2, allow_nan=False)
            destination.write("\n")
    except (OSError, ValueError, ArithmeticError) as exc:
        parser.error(str(exc))
    print(f"Trade Hawkes report: {args.output}")


if __name__ == "__main__":
    main()
