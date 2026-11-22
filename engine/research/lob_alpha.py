"""Chronological, session-aware baselines for L2 mid-price direction."""

from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby
from pathlib import Path

from .l2_features import verify_feature_csv


INPUTS = ("ofi_l1", "microprice_deviation_bps", "depth_imbalance", "spread_bps")
CLASSES = (-1, 0, 1)
DEFAULT_HORIZONS = (10, 50, 100)
LOGISTIC_PARAMS = {"solver": "newton-cg", "max_iter": 1000, "random_state": 0}
TEMPORAL_LAYERS = (32, 16)
TEMPORAL_EPOCHS = 30


@dataclass(frozen=True)
class Session:
    name: str
    manifest: dict
    rows: list[dict[str, str]]


def load_session(path: Path) -> Session:
    manifest = dict(verify_feature_csv(path))
    if manifest.get("snapshot_availability_filter") is not True:
        raise ValueError(f"{path}: rebuild features with snapshot availability filtering")
    with path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise ValueError(f"{path}: no feature rows")
    times = [int(row["received_time_ns"]) for row in rows]
    segments = [int(row["segment_id"]) for row in rows]
    if times != sorted(times) or segments != sorted(segments):
        raise ValueError(f"{path}: receive times or segment IDs go backwards")
    return Session(path.name, manifest, rows)


def examples(rows: list[dict[str, str]], horizon: int, lookback: int = 1):
    """Yield causal inputs, direction, and label delay in local receive seconds."""
    if horizon < 1 or lookback < 1:
        raise ValueError("horizon and lookback must be positive")
    for _, group in groupby(rows, key=lambda row: row["segment_id"]):
        segment = list(group)
        inputs = [tuple(float(row[column]) for column in INPUTS) for row in segment]
        for i in range(lookback - 1, len(segment) - horizon):
            now, future = segment[i], segment[i + horizon]
            mid, target = Decimal(now["mid_price"]), Decimal(future["mid_price"])
            values = tuple(value for row in inputs[i - lookback + 1 : i + 1] for value in row)
            if not all(map(math.isfinite, values)) or not all(
                price.is_finite() and price > 0 for price in (mid, target)
            ):
                raise ValueError("invalid price or model input")
            delay = (int(future["received_time_ns"]) - int(now["received_time_ns"])) / 1e9
            yield values, int(target > mid) - int(target < mid), delay


def validate_splits(splits: dict[str, list[Session]]) -> None:
    previous_end = -1
    seen = set()
    identities = set()
    for split in ("train", "validation", "test"):
        if not splits.get(split):
            raise ValueError(f"{split}: provide at least one complete session")
        for session in splits[split]:
            manifest, rows = session.manifest, session.rows
            start, end = (int(rows[i]["received_time_ns"]) for i in (0, -1))
            digest = manifest["source_sha256"]
            if digest in seen:
                raise ValueError("a source capture was reused across session inputs")
            if previous_end >= start:
                raise ValueError("sessions overlap or are not in chronological receive-time order")
            metadata = manifest.get("source_metadata") or {}
            identity = (metadata.get("venue"), metadata.get("symbol"), manifest["levels"])
            if not all(identity):
                raise ValueError("feature manifest missing venue, symbol, or depth levels")
            identities.add(identity)
            seen.add(digest)
            previous_end = end
    if len(identities) != 1:
        raise ValueError("all sessions must use the same venue, symbol, and depth levels")


def _score(actual, predicted) -> dict:
    counts = Counter(zip(actual, predicted, strict=True))
    matrix = [[counts[a, p] for p in CLASSES] for a in CLASSES]
    support = [sum(row) for row in matrix]
    predicted_support = [sum(column) for column in zip(*matrix)]
    true_positive = [matrix[i][i] for i in range(len(CLASSES))]
    return {
        "rows": len(actual),
        "support": support,
        "confusion_matrix": matrix,
        "accuracy": sum(true_positive) / len(actual),
        "macro_f1": sum(
            2 * tp / (a + p) if a + p else 0.0
            for tp, a, p in zip(true_positive, support, predicted_support)
        ) / len(CLASSES),
    }


def _training_examples(sessions: list[Session], horizon: int, lookback: int):
    training = []
    for session in sessions:
        rows = list(examples(session.rows, horizon, lookback))
        if not rows:
            raise ValueError(f"{session.name}: no usable labels at horizon {horizon}")
        training.extend(rows)
    x, y, _ = zip(*training)
    if len(set(y)) < 2:
        raise ValueError(f"horizon {horizon}: training needs at least two observed classes")
    return x, y


def _fit_logistic(x, y):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    model = make_pipeline(StandardScaler(), LogisticRegression(**LOGISTIC_PARAMS))
    return model.fit([row[-len(INPUTS):] for row in x], y)


def fit_direction_model(sessions: list[Session], horizon: int):
    x, y = _training_examples(sessions, horizon, 1)
    return _fit_logistic(x, y), y


def _fit_temporal(x, y):
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    scaled = scaler.fit_transform(x)
    model = MLPClassifier(hidden_layer_sizes=TEMPORAL_LAYERS, random_state=0)
    for _ in range(TEMPORAL_EPOCHS):
        model.partial_fit(scaled, y, classes=CLASSES)
    return lambda features: model.predict(scaler.transform(features)).tolist()


def evaluate(splits: dict[str, list[Session]], horizons=DEFAULT_HORIZONS, lookback: int = 1) -> dict:
    from sklearn import __version__ as sklearn_version

    validate_splits(splits)
    reference = splits["train"][0].manifest
    report = {
        "schema_version": 1,
        "sklearn_version": sklearn_version,
        "venue": reference["source_metadata"]["venue"],
        "symbol": reference["source_metadata"]["symbol"],
        "depth_levels": reference["levels"],
        "inputs": list(INPUTS),
        "class_order": list(CLASSES),
        "logistic_parameters": dict(LOGISTIC_PARAMS),
        "lookback_feature_rows": lookback,
        "temporal_mlp_parameters": {
            "hidden_layers": list(TEMPORAL_LAYERS), "epochs": TEMPORAL_EPOCHS, "seed": 0,
        } if lookback > 1 else None,
        "sessions": {
            split: [
                {
                    "file": s.name,
                    "feature_sha256": s.manifest["sha256"],
                    "capture_sha256": s.manifest["source_sha256"],
                    "feature_rows": len(s.rows),
                    "first_receive_ns": int(s.rows[0]["received_time_ns"]),
                    "last_receive_ns": int(s.rows[-1]["received_time_ns"]),
                }
                for s in sessions
            ]
            for split, sessions in splits.items()
        },
        "horizons": {},
    }
    for horizon in horizons:
        x, y = _training_examples(splits["train"], horizon, lookback)
        model = _fit_logistic(x, y)
        temporal = _fit_temporal(x, y) if lookback > 1 else None
        majority = max(CLASSES, key=lambda label: (y.count(label), -abs(label), -label))
        result = {"training_rows": len(y), "training_support": [y.count(c) for c in CLASSES]}
        for split in ("validation", "test"):
            actual = []
            predicted = {"majority": [], "microprice_sign": [], "logistic": []}
            if temporal is not None:
                predicted["temporal_mlp"] = []
            sessions = []
            for session in splits[split]:
                rows = list(examples(session.rows, horizon, lookback))
                if not rows:
                    raise ValueError(f"{session.name}: no usable labels at horizon {horizon}")
                features, labels, delays = zip(*rows)
                current = [row[-len(INPUTS):] for row in features]
                outputs = {
                    "majority": [majority] * len(labels),
                    "microprice_sign": [int(row[1] > 0) - int(row[1] < 0) for row in current],
                    "logistic": model.predict(current).tolist(),
                }
                if temporal is not None:
                    outputs["temporal_mlp"] = temporal(features)
                actual.extend(labels)
                for name, values in outputs.items():
                    predicted[name].extend(values)
                sessions.append({
                    "file": session.name,
                    "mean_label_delay_seconds": sum(delays) / len(delays),
                    "models": {name: _score(labels, values) for name, values in outputs.items()},
                })
            result[split] = {
                "sessions": sessions,
                "pooled": {name: _score(actual, values) for name, values in predicted.items()},
            }
        report["horizons"][str(horizon)] = result
    return report
