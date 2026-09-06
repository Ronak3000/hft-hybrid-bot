"""Fit and evaluate the leakage-controlled ApexHFT Gaussian HMM baseline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.research.hmm_regime import (
    HMMConfig,
    fit_hmm_regimes,
    verify_hmm_artifact,
)


def _integers(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(item) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated integers") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--states", default=(2, 3, 4), type=_integers)
    parser.add_argument("--seeds", default=(7, 19, 41), type=_integers)
    parser.add_argument("--iterations", default=250, type=int)
    args = parser.parse_args()

    try:
        report = fit_hmm_regimes(
            args.dataset,
            args.artifact,
            args.predictions,
            HMMConfig(
                state_counts=args.states,
                seeds=args.seeds,
                n_iter=args.iterations,
            ),
        )
        verify_hmm_artifact(args.artifact, args.dataset, args.predictions)
    except (FileExistsError, ValueError) as exc:
        parser.exit(2, f"Cannot fit HMM: {exc}\n")
    selected = report["selected"]
    print(
        f"Selected {selected['state_count']} states with seed {selected['seed']} "
        "using validation likelihood only."
    )
    print(f"Validation log likelihood/row: {selected['validation_log_likelihood_per_row']:.6f}")
    print(f"Test log likelihood/row: {report['metrics']['test']['log_likelihood_per_row']:.6f}")
    print("Regime probabilities use forward-only causal filtering.")
    print(f"Artifact: {args.artifact}")
    print(f"Predictions: {args.predictions}")


if __name__ == "__main__":
    main()
