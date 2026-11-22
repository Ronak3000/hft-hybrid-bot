"""Evaluate fixed order-book direction baselines on chronological L2 sessions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.research.lob_alpha import DEFAULT_HORIZONS, evaluate, load_session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for split in ("train", "validation", "test"):
        parser.add_argument(f"--{split}", nargs="+", type=Path, required=True)
    parser.add_argument("--horizons", nargs="+", type=int, default=DEFAULT_HORIZONS)
    parser.add_argument("--lookback", type=int, default=1, help="add a temporal MLP when above 1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if any(h < 1 for h in args.horizons) or len(set(args.horizons)) != len(args.horizons):
        parser.error("--horizons must be distinct positive integers")
    if args.lookback < 1:
        parser.error("--lookback must be positive")
    if args.output.exists():
        parser.error(f"report already exists: {args.output}")
    try:
        splits = {
            split: [load_session(path) for path in getattr(args, split)]
            for split in ("train", "validation", "test")
        }
        report = evaluate(splits, args.horizons, lookback=args.lookback)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    except ModuleNotFoundError as exc:
        if exc.name != "sklearn":
            raise
        parser.error("install the research dependency: python -m pip install -r requirements-alpha.txt")
    except (OSError, ValueError, ArithmeticError) as exc:
        parser.error(str(exc))
    print(f"Alpha baseline report: {args.output}")


if __name__ == "__main__":
    main()
