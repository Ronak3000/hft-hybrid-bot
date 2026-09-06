"""Build a deterministic, causal feature CSV from a verified L2 capture."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.research import extract_feature_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--levels",
        default=5,
        type=int,
        help="number of price levels per side used for depth imbalance",
    )
    args = parser.parse_args()
    if args.levels <= 0:
        parser.error("--levels must be positive")

    manifest = extract_feature_csv(args.capture, args.output, args.levels)
    print(f"Feature rows: {manifest['row_count']}")
    print(f"Depth levels: {manifest['levels']}")
    print(f"Source SHA-256: {manifest['source_sha256']}")
    print(f"Feature SHA-256: {manifest['sha256']}")
    print(f"Features: {args.output}")
    print(f"Manifest: {args.output}.manifest.json")


if __name__ == "__main__":
    main()
