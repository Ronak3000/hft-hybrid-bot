"""Verify and deterministically replay an ApexHFT L2 capture."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.market_data import replay_capture, verify_capture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()

    manifest = verify_capture(args.capture)
    result = replay_capture(args.capture)
    print(f"Integrity: verified ({manifest['sha256']})")
    print(f"Records: {manifest['record_count']}")
    print(f"Snapshots: {result.snapshots}")
    print(f"Applied deltas: {result.applied_deltas}")
    print(f"Stale deltas: {result.stale_deltas}")
    print(f"Detected gaps: {result.gaps}")
    print(f"Accepted public trades: {result.accepted_trades}")
    print(f"Duplicate public trades: {result.duplicate_trades}")
    print(f"Out-of-order public trades: {result.out_of_order_trades}")
    print(f"Observed trade-ID gaps: {result.trade_id_gaps}")
    print(f"Synchronized: {result.book.synchronized}")
    print(f"Last update ID: {result.book.last_update_id}")
    print(f"Best bid / ask: {result.book.best_bid} / {result.book.best_ask}")
    print(f"State digest: {result.book.state_digest()}")


if __name__ == "__main__":
    main()
