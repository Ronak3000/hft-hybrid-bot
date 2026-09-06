"""Leakage-controlled Gaussian HMM selection and causal regime filtering."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import hmmlearn
import numpy as np
import sklearn
from hmmlearn.hmm import GaussianHMM

from .dataset import SPLIT_COLUMNS, verify_split_csv


HMM_ARTIFACT_SCHEMA_VERSION = 1
PREDICTION_SCHEMA_VERSION = 1
DEFAULT_HMM_FEATURES = (
    "spread_bps",
    "microprice_deviation_bps",
    "depth_imbalance",
    "ofi_l1",
)
ALLOWED_HMM_FEATURES = DEFAULT_HMM_FEATURES + (
    "bid_levels_changed",
    "ask_levels_changed",
)


@dataclass(frozen=True, slots=True)
class HMMConfig:
    state_counts: tuple[int, ...] = (2, 3, 4)
    seeds: tuple[int, ...] = (7, 19, 41)
    features: tuple[str, ...] = DEFAULT_HMM_FEATURES
    covariance_type: str = "diag"
    n_iter: int = 250
    tolerance: float = 1e-4
    min_covar: float = 1e-3
    min_samples_per_state: int = 20
    min_state_occupancy: float = 0.01

    def validate(self) -> None:
        if not self.state_counts or any(count < 2 for count in self.state_counts):
            raise ValueError("state_counts must contain integers of at least two")
        if len(set(self.state_counts)) != len(self.state_counts):
            raise ValueError("state_counts must not contain duplicates")
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be non-empty and unique")
        if not self.features or len(set(self.features)) != len(self.features):
            raise ValueError("features must be non-empty and unique")
        invalid = set(self.features) - set(ALLOWED_HMM_FEATURES)
        if invalid:
            raise ValueError(f"unsupported or non-causal HMM features: {sorted(invalid)}")
        if self.covariance_type != "diag":
            raise ValueError("only diagonal covariance is supported in this baseline")
        if self.n_iter <= 0 or self.tolerance <= 0 or self.min_covar <= 0:
            raise ValueError("iteration and numerical parameters must be positive")
        if self.min_samples_per_state < 2:
            raise ValueError("min_samples_per_state must be at least two")
        if not 0 <= self.min_state_occupancy < 1:
            raise ValueError("min_state_occupancy must be in [0, 1)")


@dataclass(slots=True)
class _Partition:
    rows: list[dict[str, str]]
    matrix: np.ndarray
    lengths: list[int]


def _exclusive(path: str | Path) -> Path:
    result = Path(path)
    result.parent.mkdir(parents=True, exist_ok=True)
    if result.exists():
        raise FileExistsError(f"output already exists: {result}")
    return result


def _sequence_lengths(rows: Sequence[Mapping[str, str]]) -> list[int]:
    lengths: list[int] = []
    previous: tuple[str, str] | None = None
    current = 0
    for row in rows:
        key = (row["split"], row["segment_id"])
        if previous is not None and key != previous:
            lengths.append(current)
            current = 0
        current += 1
        previous = key
    if current:
        lengths.append(current)
    return lengths


def _load_dataset(
    path: str | Path, features: Sequence[str]
) -> tuple[Mapping[str, Any], dict[str, _Partition]]:
    manifest = verify_split_csv(path)
    grouped: dict[str, list[dict[str, str]]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    with Path(path).open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != SPLIT_COLUMNS:
            raise ValueError("dataset columns do not match the split schema")
        for row in reader:
            grouped[row["split"]].append(row)

    partitions: dict[str, _Partition] = {}
    for name, rows in grouped.items():
        if not rows:
            raise ValueError(f"{name} split is empty; collect more data before fitting")
        matrix = np.asarray(
            [[float(row[feature]) for feature in features] for row in rows],
            dtype=np.float64,
        )
        if matrix.ndim != 2 or not np.isfinite(matrix).all():
            raise ValueError(f"{name} split contains non-finite model inputs")
        partitions[name] = _Partition(rows, matrix, _sequence_lengths(rows))
    return manifest, partitions


def _fit_scaler(train: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[int]]:
    mean = np.mean(train, axis=0, dtype=np.float64)
    scale = np.std(train, axis=0, dtype=np.float64)
    constant = np.flatnonzero(scale < 1e-12).tolist()
    scale = scale.copy()
    scale[constant] = 1.0
    return mean, scale, constant


def _diag_covariances(model: GaussianHMM) -> np.ndarray:
    covariances = np.asarray(model.covars_, dtype=np.float64)
    if covariances.ndim == 3:
        covariances = np.diagonal(covariances, axis1=1, axis2=2)
    if covariances.ndim != 2:
        raise ValueError("unexpected GaussianHMM covariance shape")
    return covariances


def _logsumexp(values: np.ndarray, axis: int | None = None) -> np.ndarray:
    maximum = np.max(values, axis=axis, keepdims=True)
    finite = np.isfinite(maximum)
    shifted = np.where(finite, values - maximum, values)
    total = np.sum(np.exp(shifted), axis=axis, keepdims=True)
    result = np.where(finite, maximum + np.log(total), maximum)
    return np.squeeze(result, axis=axis)


def forward_filter(
    observations: np.ndarray,
    lengths: Sequence[int],
    start_probability: np.ndarray,
    transition_matrix: np.ndarray,
    means: np.ndarray,
    diagonal_covariances: np.ndarray,
) -> np.ndarray:
    """Return causal P(state_t | observations_0..t), resetting per sequence."""
    observations = np.asarray(observations, dtype=np.float64)
    start_probability = np.asarray(start_probability, dtype=np.float64)
    transition_matrix = np.asarray(transition_matrix, dtype=np.float64)
    means = np.asarray(means, dtype=np.float64)
    diagonal_covariances = np.asarray(diagonal_covariances, dtype=np.float64)
    if sum(lengths) != len(observations) or any(length <= 0 for length in lengths):
        raise ValueError("sequence lengths must be positive and sum to observations")
    if np.any(diagonal_covariances <= 0):
        raise ValueError("Gaussian covariances must be positive")

    with np.errstate(divide="ignore"):
        log_start = np.log(start_probability)
        log_transition = np.log(transition_matrix)
    dimension = observations.shape[1]
    log_normalizer = dimension * math.log(2 * math.pi)
    delta = observations[:, None, :] - means[None, :, :]
    log_emission = -0.5 * (
        log_normalizer
        + np.sum(np.log(diagonal_covariances), axis=1)[None, :]
        + np.sum(delta * delta / diagonal_covariances[None, :, :], axis=2)
    )

    probabilities = np.empty((len(observations), len(start_probability)), dtype=np.float64)
    offset = 0
    for length in lengths:
        log_alpha = log_start + log_emission[offset]
        log_alpha -= _logsumexp(log_alpha)
        probabilities[offset] = np.exp(log_alpha)
        for index in range(offset + 1, offset + length):
            log_alpha = (
                _logsumexp(log_alpha[:, None] + log_transition, axis=0)
                + log_emission[index]
            )
            log_alpha -= _logsumexp(log_alpha)
            probabilities[index] = np.exp(log_alpha)
        offset += length
    return probabilities


def _candidate(
    train: _Partition,
    validation: _Partition,
    state_count: int,
    seed: int,
    config: HMMConfig,
) -> tuple[dict[str, Any], GaussianHMM | None]:
    diagnostic: dict[str, Any] = {
        "seed": seed,
        "state_count": state_count,
    }
    required = state_count * config.min_samples_per_state
    if len(train.matrix) < required:
        diagnostic.update(
            valid=False,
            error=f"requires at least {required} training rows",
        )
        return diagnostic, None
    try:
        model = GaussianHMM(
            n_components=state_count,
            covariance_type=config.covariance_type,
            min_covar=config.min_covar,
            n_iter=config.n_iter,
            tol=config.tolerance,
            random_state=seed,
            implementation="log",
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model.fit(train.matrix, lengths=train.lengths)
        covariances = _diag_covariances(model)
        probabilities = forward_filter(
            train.matrix,
            train.lengths,
            model.startprob_,
            model.transmat_,
            model.means_,
            covariances,
        )
        occupancy = probabilities.mean(axis=0)
        history = [float(value) for value in model.monitor_.history]
        monotonic = all(
            current + 1e-6 >= previous
            for previous, current in zip(history, history[1:])
        )
        converged = bool(model.monitor_.converged) and monotonic
        minimum_occupancy = float(np.min(occupancy))
        diagnostic.update(
            converged=converged,
            iterations=int(model.monitor_.iter),
            likelihood_history_tail=history[-5:],
            likelihood_monotonic=monotonic,
            min_train_occupancy=minimum_occupancy,
            train_log_likelihood_per_row=float(
                model.score(train.matrix, lengths=train.lengths) / len(train.matrix)
            ),
            validation_log_likelihood_per_row=float(
                model.score(validation.matrix, lengths=validation.lengths)
                / len(validation.matrix)
            ),
            valid=converged and minimum_occupancy >= config.min_state_occupancy,
            warning_count=len(caught),
        )
        if not diagnostic["valid"]:
            diagnostic["error"] = "non-convergence or collapsed training state"
        return diagnostic, model
    except (FloatingPointError, ValueError) as exc:
        diagnostic.update(valid=False, error=f"{type(exc).__name__}: {exc}")
        return diagnostic, None


def _canonical_order(means: np.ndarray) -> np.ndarray:
    return np.asarray(
        sorted(range(len(means)), key=lambda state: tuple(means[state].tolist())),
        dtype=np.int64,
    )


def _occupancy(probabilities: np.ndarray, order: np.ndarray) -> list[float]:
    return probabilities[:, order].mean(axis=0).astype(float).tolist()


def _state_summaries(
    partition: _Partition,
    probabilities: np.ndarray,
    order: np.ndarray,
    features: Sequence[str],
) -> list[dict[str, Any]]:
    canonical = probabilities[:, order]
    hard_states = np.argmax(canonical, axis=1)
    summaries: list[dict[str, Any]] = []
    labels = np.asarray(
        [float(row["label_mid_return_bps"]) for row in partition.rows],
        dtype=np.float64,
    )
    for state in range(canonical.shape[1]):
        selected = hard_states == state
        count = int(np.sum(selected))
        summaries.append(
            {
                "count": count,
                "mean_features": {
                    feature: (float(np.mean(partition.matrix[selected, index])) if count else None)
                    for index, feature in enumerate(features)
                },
                "mean_label_mid_return_bps": (
                    float(np.mean(labels[selected])) if count else None
                ),
                "regime_id": state,
            }
        )
    return summaries


def _canonical_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(
            json.dumps(dict(payload), allow_nan=False, indent=2, sort_keys=True) + "\n"
        )
        destination.flush()
        os.fsync(destination.fileno())


def fit_hmm_regimes(
    dataset_path: str | Path,
    artifact_path: str | Path,
    predictions_path: str | Path,
    config: HMMConfig = HMMConfig(),
) -> Mapping[str, Any]:
    """Select on validation, freeze, then emit causal test-safe diagnostics."""
    config.validate()
    artifact = _exclusive(artifact_path)
    artifact_manifest = _exclusive(f"{artifact}.manifest.json")
    predictions = _exclusive(predictions_path)
    dataset_manifest, partitions = _load_dataset(dataset_path, config.features)

    mean, scale, constant = _fit_scaler(partitions["train"].matrix)
    scaled: dict[str, _Partition] = {}
    for name, partition in partitions.items():
        scaled[name] = _Partition(
            partition.rows,
            (partition.matrix - mean) / scale,
            partition.lengths,
        )

    candidates: list[dict[str, Any]] = []
    fitted: dict[tuple[int, int], GaussianHMM] = {}
    for state_count in config.state_counts:
        for seed in config.seeds:
            diagnostic, model = _candidate(
                scaled["train"], scaled["validation"], state_count, seed, config
            )
            candidates.append(diagnostic)
            if diagnostic["valid"] and model is not None:
                fitted[(state_count, seed)] = model
    valid = [candidate for candidate in candidates if candidate.get("valid")]
    if not valid:
        raise ValueError("no HMM candidate converged without a collapsed state")
    selected = max(
        valid,
        key=lambda item: (
            item["validation_log_likelihood_per_row"],
            -item["state_count"],
            -item["seed"],
        ),
    )
    model = fitted[(selected["state_count"], selected["seed"])]
    covariances = _diag_covariances(model)
    order = _canonical_order(model.means_)

    filtered: dict[str, np.ndarray] = {}
    metrics: dict[str, Any] = {}
    for name, partition in scaled.items():
        filtered[name] = forward_filter(
            partition.matrix,
            partition.lengths,
            model.startprob_,
            model.transmat_,
            model.means_,
            covariances,
        )
        metrics[name] = {
            "filtered_occupancy": _occupancy(filtered[name], order),
            "log_likelihood_per_row": float(
                model.score(partition.matrix, lengths=partition.lengths)
                / len(partition.matrix)
            ),
            "rows": len(partition.matrix),
            "state_summaries": _state_summaries(
                partitions[name], filtered[name], order, config.features
            ),
        }

    probability_columns = tuple(
        f"regime_probability_{state}" for state in range(model.n_components)
    )
    prediction_columns = (
        "segment_id",
        "event_time_ms",
        "update_id",
        "split",
        "label_mid_return_bps",
        "regime_id",
        "regime_probability",
    ) + probability_columns
    with predictions.open("x", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=prediction_columns, lineterminator="\n")
        writer.writeheader()
        for name in ("train", "validation", "test"):
            canonical = filtered[name][:, order]
            for row, probabilities in zip(partitions[name].rows, canonical, strict=True):
                regime = int(np.argmax(probabilities))
                output: dict[str, Any] = {
                    "segment_id": row["segment_id"],
                    "event_time_ms": row["event_time_ms"],
                    "update_id": row["update_id"],
                    "split": name,
                    "label_mid_return_bps": row["label_mid_return_bps"],
                    "regime_id": regime,
                    "regime_probability": format(float(probabilities[regime]), ".17g"),
                }
                output.update(
                    {
                        column: format(float(probabilities[index]), ".17g")
                        for index, column in enumerate(probability_columns)
                    }
                )
                writer.writerow(output)
        destination.flush()
        os.fsync(destination.fileno())
    prediction_bytes = predictions.read_bytes()

    canonical_start = model.startprob_[order]
    canonical_transition = model.transmat_[np.ix_(order, order)]
    canonical_means = model.means_[order]
    canonical_covariances = covariances[order]
    stability: list[dict[str, Any]] = []
    for state_count in config.state_counts:
        scores = [
            candidate["validation_log_likelihood_per_row"]
            for candidate in valid
            if candidate["state_count"] == state_count
        ]
        stability.append(
            {
                "state_count": state_count,
                "valid_seed_count": len(scores),
                "validation_log_likelihood_mean": (
                    float(np.mean(scores)) if scores else None
                ),
                "validation_log_likelihood_range": (
                    float(max(scores) - min(scores)) if scores else None
                ),
                "validation_log_likelihood_std": (
                    float(np.std(scores)) if scores else None
                ),
            }
        )

    report: dict[str, Any] = {
        "artifact_schema_version": HMM_ARTIFACT_SCHEMA_VERSION,
        "candidate_diagnostics": candidates,
        "configuration": {
            "covariance_type": config.covariance_type,
            "features": list(config.features),
            "min_covar": config.min_covar,
            "min_samples_per_state": config.min_samples_per_state,
            "min_state_occupancy": config.min_state_occupancy,
            "n_iter": config.n_iter,
            "seeds": list(config.seeds),
            "state_counts": list(config.state_counts),
            "tolerance": config.tolerance,
        },
        "evaluation_protocol": {
            "inference": "forward_filter_only",
            "model_selection": "maximum validation log likelihood per row",
            "scaler_fit": "train_only",
            "test_used_for_selection": False,
        },
        "libraries": {
            "hmmlearn": hmmlearn.__version__,
            "numpy": np.__version__,
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
        },
        "metrics": metrics,
        "model": {
            "covariances": canonical_covariances.tolist(),
            "means": canonical_means.tolist(),
            "start_probability": canonical_start.tolist(),
            "transition_matrix": canonical_transition.tolist(),
        },
        "prediction_file": predictions.name,
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "prediction_sha256": hashlib.sha256(prediction_bytes).hexdigest(),
        "scaler": {
            "constant_feature_indices": constant,
            "fit_partition": "train",
            "mean": mean.tolist(),
            "scale": scale.tolist(),
        },
        "selected": dict(selected),
        "selection_stability": stability,
        "source_dataset": Path(dataset_path).name,
        "source_dataset_sha256": dataset_manifest["sha256"],
    }
    _canonical_json(artifact, report)
    artifact_bytes = artifact.read_bytes()
    _canonical_json(
        artifact_manifest,
        {
            "artifact_file": artifact.name,
            "artifact_schema_version": HMM_ARTIFACT_SCHEMA_VERSION,
            "byte_count": len(artifact_bytes),
            "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            "source_dataset_sha256": dataset_manifest["sha256"],
        },
    )
    return report


def verify_hmm_artifact(
    artifact_path: str | Path,
    dataset_path: str | Path | None = None,
    predictions_path: str | Path | None = None,
) -> Mapping[str, Any]:
    artifact = Path(artifact_path)
    manifest_path = Path(f"{artifact}.manifest.json")
    try:
        raw = artifact.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read HMM artifact or manifest: {exc}") from exc
    if manifest.get("artifact_schema_version") != HMM_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported HMM artifact schema")
    if report.get("artifact_schema_version") != HMM_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("HMM report schema does not match")
    if manifest.get("artifact_file") != artifact.name:
        raise ValueError("HMM artifact filename does not match manifest")
    if manifest.get("byte_count") != len(raw):
        raise ValueError("HMM artifact byte count does not match manifest")
    if manifest.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("HMM artifact SHA-256 does not match manifest")
    if dataset_path is not None:
        dataset = verify_split_csv(dataset_path)
        if report.get("source_dataset_sha256") != dataset.get("sha256"):
            raise ValueError("HMM artifact does not match the source dataset")
    if predictions_path is not None:
        predictions = Path(predictions_path)
        if report.get("prediction_file") != predictions.name:
            raise ValueError("prediction filename does not match HMM artifact")
        if report.get("prediction_sha256") != hashlib.sha256(predictions.read_bytes()).hexdigest():
            raise ValueError("prediction SHA-256 does not match HMM artifact")
    return report
