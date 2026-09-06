"""Fit Avellaneda–Stoikov inputs using explicitly selected training captures."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.research import calibrate_avellaneda_stoikov, write_calibration


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-captures", type=Path, nargs="+", required=True)
    parser.add_argument("--distances", type=Decimal, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    calibration = calibrate_avellaneda_stoikov(
        args.training_captures, args.distances
    )
    write_calibration(calibration, args.output)
    print(f"Training captures: {len(args.training_captures)}")
    print(f"Volatility / sqrt(second): {calibration.volatility_per_sqrt_second}")
    print(f"Intensity decay k: {calibration.intensity_decay}")
    print(f"Intensity scale A / second: {calibration.intensity_scale_per_second}")
    print(f"Intensity fit R-squared: {calibration.intensity_fit_r_squared}")
    print(f"Calibration: {args.output}")


if __name__ == "__main__":
    main()
