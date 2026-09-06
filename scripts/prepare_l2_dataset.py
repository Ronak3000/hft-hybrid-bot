"""Build timestamp labels and leakage-safe chronological splits."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.research import (
    build_forward_return_labels,
    chronological_split,
    verify_split_csv,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("--horizon-ms", required=True, type=int)
    parser.add_argument("--labeled-output", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--train-ratio", default="0.6")
    parser.add_argument("--validation-ratio", default="0.2")
    args = parser.parse_args()

    labels = build_forward_return_labels(
        args.features, args.labeled_output, args.horizon_ms
    )
    split = chronological_split(
        args.labeled_output,
        args.output,
        train_ratio=args.train_ratio,
        validation_ratio=args.validation_ratio,
    )
    verify_split_csv(args.output, args.labeled_output)
    print(f"Labeled rows: {labels['row_count']}")
    print(
        "Dropped without a same-segment future: "
        f"{labels['dropped_without_same_segment_future']}"
    )
    print(f"Split counts: {split['counts']}")
    if any(count == 0 for count in split["counts"].values()):
        print("WARNING: at least one split is empty; collect more data before modeling.")
    print(f"Purged at time boundaries: {split['purged_boundary_crossing_labels']}")
    print(f"Dataset SHA-256: {split['sha256']}")
    print(f"Dataset: {args.output}")


if __name__ == "__main__":
    main()
