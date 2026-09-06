"""Capture one planned study session using its frozen collection settings."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.research import (
    audit_study,
    load_study_plan,
    planned_capture_path,
)
from scripts.capture_binance_l2 import capture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()
    try:
        plan = load_study_plan(args.plan)
        selected = next(
            item for item in plan["sessions"] if item["session_id"] == args.session_id
        )
    except StopIteration:
        parser.error(f"unknown study session: {args.session_id}")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    audit = audit_study(args.plan, project_root=PROJECT_ROOT)
    preceding = [
        item for item in audit["sessions"] if item["ordinal"] < selected["ordinal"]
    ]
    invalid_preceding = [item for item in preceding if item["status"] != "valid"]
    if invalid_preceding:
        parser.error(
            "capture earlier valid sessions first; blocked by "
            + ", ".join(item["session_id"] for item in invalid_preceding)
        )
    output = planned_capture_path(plan, args.session_id, PROJECT_ROOT)
    if output.exists() or Path(f"{output}.manifest.json").exists():
        parser.error(f"planned session already exists: {output}")

    configuration = plan["capture_configuration"]
    asyncio.run(
        capture(
            configuration["symbol"],
            output,
            configuration["events_per_session"],
            configuration["depth_limit"],
            configuration["max_reconnects"],
        )
    )
    refreshed = audit_study(args.plan, project_root=PROJECT_ROOT)
    result = next(
        item for item in refreshed["sessions"] if item["session_id"] == args.session_id
    )
    if result["status"] != "valid":
        parser.error(
            f"capture completed but failed declared quality rules: {result['status']}"
        )
    print(f"Validated study session: {args.session_id}")


if __name__ == "__main__":
    main()
