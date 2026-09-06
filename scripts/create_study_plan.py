"""Create an immutable chronological market-data collection plan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.research import create_study_plan, write_study_plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-name", required=True)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--capture-directory", required=True)
    parser.add_argument("--training-sessions", type=int, default=10)
    parser.add_argument("--validation-sessions", type=int, default=5)
    parser.add_argument("--test-sessions", type=int, default=10)
    parser.add_argument("--events-per-session", type=int, default=100_000)
    parser.add_argument(
        "--depth-limit", type=int, default=1_000, choices=(100, 500, 1000, 5000)
    )
    parser.add_argument("--max-reconnects", type=int, default=8)
    parser.add_argument("--min-trades-per-session", type=int, default=1_000)
    parser.add_argument("--max-depth-gaps-per-session", type=int, default=0)
    parser.add_argument("--max-trade-gaps-per-session", type=int, default=0)
    parser.add_argument("--max-disconnects-per-session", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = create_study_plan(
            study_name=args.study_name,
            symbol=args.symbol,
            capture_directory=args.capture_directory,
            training_sessions=args.training_sessions,
            validation_sessions=args.validation_sessions,
            test_sessions=args.test_sessions,
            events_per_session=args.events_per_session,
            depth_limit=args.depth_limit,
            max_reconnects=args.max_reconnects,
            min_trades_per_session=args.min_trades_per_session,
            max_depth_gaps_per_session=args.max_depth_gaps_per_session,
            max_trade_gaps_per_session=args.max_trade_gaps_per_session,
            max_disconnects_per_session=args.max_disconnects_per_session,
        )
        write_study_plan(plan, args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Study: {plan['study_name']}")
    print(f"Planned sessions: {len(plan['sessions'])}")
    print(f"Plan: {args.output}")
    print(f"Manifest: {args.output}.manifest.json")


if __name__ == "__main__":
    main()
