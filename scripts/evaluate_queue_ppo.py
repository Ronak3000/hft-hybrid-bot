"""Evaluate integrity-checked PPO seeds on validation or final test captures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.research.ppo_evaluation import evaluate_ppo_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), required=True)
    parser.add_argument("--models", type=Path, nargs="+", required=True)
    parser.add_argument("--confirm-final-test", action="store_true")
    parser.add_argument("--bootstrap-seed", type=int, default=17)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output already exists")
    if args.split == "test" and not args.confirm_final_test:
        parser.error("test split requires --confirm-final-test")
    if args.split != "test" and args.confirm_final_test:
        parser.error("--confirm-final-test is valid only with --split test")

    try:
        from stable_baselines3 import PPO

        report = evaluate_ppo_artifacts(
            args.plan,
            args.split,
            tuple(args.models),
            project_root=PROJECT_ROOT,
            predictor_loader=lambda path: PPO.load(str(path), device="cpu"),
            allow_test=args.confirm_final_test,
            bootstrap_seed=args.bootstrap_seed,
            bootstrap_samples=args.bootstrap_samples,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Models: {report['model_count']}")
    print(f"{args.split.title()} sessions: {report['session_count']}")
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
