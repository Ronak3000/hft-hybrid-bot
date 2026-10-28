"""Export real training captures into a backend-independent browser replay."""

from __future__ import annotations

import argparse
from decimal import Decimal
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.research.replay_demo import export_training_demo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "web/public/replays")
    parser.add_argument("--ppo-metadata", type=Path, help="Verified training-only PPO sidecar for this study")
    parser.add_argument("--entry-fee-buffer-bps", type=Decimal, help="Explicit external entry-cost overlay; does not retrain or modify model metadata")
    args = parser.parse_args()
    try:
        catalog = export_training_demo(args.plan, PROJECT_ROOT, args.output, ppo_metadata=args.ppo_metadata, entry_fee_buffer_bps=args.entry_fee_buffer_bps)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Exported {len(catalog['sessions'])} segments from real training captures.")
    print(f"Catalog: {args.output / 'catalog.json'}")
    print("Open /replay in the web app. No validation/test captures were used.")


if __name__ == "__main__":
    main()
