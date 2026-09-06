"""Audit planned captures for integrity, chronology, and data quality."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.research import audit_study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="return success while valid planned sessions are still missing",
    )
    args = parser.parse_args()
    try:
        report = audit_study(args.plan, project_root=PROJECT_ROOT)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as destination:
            destination.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Study status: {report['status']}")
    print(
        "Sessions: "
        f"{report['valid_sessions']} valid, "
        f"{report['missing_sessions']} missing, "
        f"{report['rejected_sessions']} rejected"
    )
    print(f"Audit: {args.output}")
    if report["status"] == "fail" or (
        report["status"] == "incomplete" and not args.allow_incomplete
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
