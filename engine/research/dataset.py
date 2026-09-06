"""Leakage-safe labels and chronological splits for L2 research."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import deque
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, Iterator, Mapping

from .l2_features import (
    FEATURE_COLUMNS,
    FEATURE_DECIMAL_CONTEXT,
    verify_feature_csv,
)


LABEL_SCHEMA_VERSION = 1
SPLIT_SCHEMA_VERSION = 1
LABEL_COLUMNS = FEATURE_COLUMNS + (
    "label_horizon_ms",
    "label_target_segment_id",
    "label_target_event_time_ms",
    "label_target_update_id",
    "label_realized_horizon_ms",
    "label_mid_return_bps",
)
SPLIT_COLUMNS = LABEL_COLUMNS + ("split",)


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if parsed <= 0 or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"{field} must be a positive integer")
    return parsed


def _decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _exclusive_output(path: str | Path) -> tuple[Path, Path]:
    output = Path(path)
    manifest = Path(f"{output}.manifest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    if manifest.exists():
        raise FileExistsError(f"manifest already exists: {manifest}")
    return output, manifest


def _write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n")
        destination.flush()
        os.fsync(destination.fileno())


def _feature_rows(path: str | Path) -> Iterator[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != FEATURE_COLUMNS:
            raise ValueError("feature CSV columns do not match the feature schema")
        yield from reader


def _labeled_rows(path: str | Path) -> Iterator[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != LABEL_COLUMNS:
            raise ValueError("labeled CSV columns do not match the label schema")
        yield from reader


def build_forward_return_labels(
    feature_path: str | Path,
    output_path: str | Path,
    horizon_ms: int,
) -> Mapping[str, Any]:
    """Label each row using the first same-segment observation at the horizon."""
    horizon = _positive_int(horizon_ms, "horizon_ms")
    feature_manifest = verify_feature_csv(feature_path)
    output, manifest_path = _exclusive_output(output_path)
    pending: deque[tuple[dict[str, str], int, Decimal]] = deque()
    current_segment: int | None = None
    previous_event_time: int | None = None
    row_count = 0
    dropped_without_future = 0
    first_labeled_time: int | None = None
    last_labeled_time: int | None = None

    with output.open("x", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=LABEL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in _feature_rows(feature_path):
            segment = int(row["segment_id"])
            event_time = int(row["event_time_ms"])
            mid = _decimal(row["mid_price"], "mid_price")
            if previous_event_time is not None and event_time < previous_event_time:
                raise ValueError("feature rows must be globally chronological")
            previous_event_time = event_time

            if current_segment is None or segment != current_segment:
                if current_segment is not None and segment <= current_segment:
                    raise ValueError("segment_id must increase chronologically")
                dropped_without_future += len(pending)
                pending.clear()
                current_segment = segment

            while pending and event_time >= pending[0][1] + horizon:
                source_row, source_time, source_mid = pending.popleft()
                with localcontext(FEATURE_DECIMAL_CONTEXT):
                    return_bps = (mid - source_mid) / source_mid * Decimal(10_000)
                labeled: dict[str, str | int] = dict(source_row)
                labeled.update(
                    {
                        "label_horizon_ms": horizon,
                        "label_target_segment_id": segment,
                        "label_target_event_time_ms": event_time,
                        "label_target_update_id": row["update_id"],
                        "label_realized_horizon_ms": event_time - source_time,
                        "label_mid_return_bps": _decimal_text(return_bps),
                    }
                )
                writer.writerow(labeled)
                row_count += 1
                first_labeled_time = (
                    source_time if first_labeled_time is None else first_labeled_time
                )
                last_labeled_time = source_time
            pending.append((row, event_time, mid))

        dropped_without_future += len(pending)
        destination.flush()
        os.fsync(destination.fileno())

    raw = output.read_bytes()
    manifest: dict[str, Any] = {
        "byte_count": len(raw),
        "columns": list(LABEL_COLUMNS),
        "dropped_without_same_segment_future": dropped_without_future,
        "horizon_ms": horizon,
        "first_event_time_ms": first_labeled_time,
        "last_event_time_ms": last_labeled_time,
        "label_file": output.name,
        "label_schema_version": LABEL_SCHEMA_VERSION,
        "row_count": row_count,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_feature_file": Path(feature_path).name,
        "source_feature_sha256": feature_manifest["sha256"],
        "source_capture_sha256": feature_manifest["source_sha256"],
    }
    _write_manifest(manifest_path, manifest)
    return manifest


def verify_labeled_csv(
    label_path: str | Path, feature_path: str | Path | None = None
) -> Mapping[str, Any]:
    label = Path(label_path)
    manifest_path = Path(f"{label}.manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw = label.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read labeled dataset or manifest: {exc}") from exc
    if manifest.get("label_schema_version") != LABEL_SCHEMA_VERSION:
        raise ValueError("unsupported label schema version")
    if manifest.get("label_file") != label.name:
        raise ValueError("label filename does not match manifest")
    if manifest.get("columns") != list(LABEL_COLUMNS):
        raise ValueError("label columns do not match schema")
    if manifest.get("byte_count") != len(raw):
        raise ValueError("label byte count does not match manifest")
    if manifest.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("label SHA-256 does not match manifest")
    horizon = _positive_int(manifest.get("horizon_ms"), "manifest horizon_ms")
    row_count = 0
    first_time: int | None = None
    last_time: int | None = None
    for row in _labeled_rows(label):
        event_time = int(row["event_time_ms"])
        target_time = int(row["label_target_event_time_ms"])
        target_segment = int(row["label_target_segment_id"])
        source_segment = int(row["segment_id"])
        target_update_id = int(row["label_target_update_id"])
        source_update_id = int(row["update_id"])
        realized = int(row["label_realized_horizon_ms"])
        if last_time is not None and event_time < last_time:
            raise ValueError("labeled rows must be chronological")
        if target_time - event_time != realized or realized < horizon:
            raise ValueError("label timing fields are inconsistent")
        if target_segment != source_segment or target_update_id <= source_update_id:
            raise ValueError("label target crosses a segment or is not forward in sequence")
        first_time = event_time if first_time is None else first_time
        last_time = event_time
        row_count += 1
    if manifest.get("row_count") != row_count:
        raise ValueError("label row count does not match manifest")
    if manifest.get("first_event_time_ms") != first_time:
        raise ValueError("first label time does not match manifest")
    if manifest.get("last_event_time_ms") != last_time:
        raise ValueError("last label time does not match manifest")
    if feature_path is not None:
        source = verify_feature_csv(feature_path)
        if manifest.get("source_feature_sha256") != source.get("sha256"):
            raise ValueError("labels do not match the source feature file")
        if manifest.get("source_feature_file") != Path(feature_path).name:
            raise ValueError("source feature filename does not match label manifest")
    return manifest


def _ratios(train_ratio: Any, validation_ratio: Any) -> tuple[Decimal, Decimal]:
    train = _decimal(train_ratio, "train_ratio")
    validation = _decimal(validation_ratio, "validation_ratio")
    if train <= 0 or validation <= 0 or train + validation >= 1:
        raise ValueError("ratios must be positive and leave a positive test interval")
    return train, validation


def chronological_split(
    label_path: str | Path,
    output_path: str | Path,
    train_ratio: Any = "0.6",
    validation_ratio: Any = "0.2",
) -> Mapping[str, Any]:
    """Assign time-based splits and purge labels crossing split boundaries."""
    train, validation = _ratios(train_ratio, validation_ratio)
    label_manifest = verify_labeled_csv(label_path)
    output, manifest_path = _exclusive_output(output_path)

    first_time = label_manifest.get("first_event_time_ms")
    last_time = label_manifest.get("last_event_time_ms")
    if first_time is None or last_time is None or first_time == last_time:
        raise ValueError("at least two distinct event times are required for splitting")

    with localcontext(FEATURE_DECIMAL_CONTEXT):
        duration = Decimal(last_time - first_time + 1)
        train_boundary = first_time + int(duration * train)
        validation_boundary = first_time + int(duration * (train + validation))
    if not first_time < train_boundary < validation_boundary <= last_time:
        raise ValueError("dataset time span is too short for the requested ratios")

    counts = {"train": 0, "validation": 0, "test": 0}
    purged = 0
    with output.open("x", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=SPLIT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in _labeled_rows(label_path):
            event_time = int(row["event_time_ms"])
            target_time = int(row["label_target_event_time_ms"])
            if event_time < train_boundary:
                if target_time >= train_boundary:
                    purged += 1
                    continue
                split = "train"
            elif event_time < validation_boundary:
                if target_time >= validation_boundary:
                    purged += 1
                    continue
                split = "validation"
            else:
                split = "test"
            writer.writerow({**row, "split": split})
            counts[split] += 1
        destination.flush()
        os.fsync(destination.fileno())

    raw = output.read_bytes()
    manifest: dict[str, Any] = {
        "byte_count": len(raw),
        "columns": list(SPLIT_COLUMNS),
        "counts": counts,
        "purged_boundary_crossing_labels": purged,
        "row_count": sum(counts.values()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_capture_sha256": label_manifest["source_capture_sha256"],
        "source_feature_sha256": label_manifest["source_feature_sha256"],
        "source_label_file": Path(label_path).name,
        "source_label_sha256": label_manifest["sha256"],
        "split_file": output.name,
        "split_schema_version": SPLIT_SCHEMA_VERSION,
        "test_ratio": _decimal_text(Decimal(1) - train - validation),
        "train_boundary_event_time_ms": train_boundary,
        "train_ratio": _decimal_text(train),
        "validation_boundary_event_time_ms": validation_boundary,
        "validation_ratio": _decimal_text(validation),
    }
    _write_manifest(manifest_path, manifest)
    return manifest


def verify_split_csv(
    split_path: str | Path, label_path: str | Path | None = None
) -> Mapping[str, Any]:
    split_file = Path(split_path)
    manifest_path = Path(f"{split_file}.manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw = split_file.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read split dataset or manifest: {exc}") from exc
    if manifest.get("split_schema_version") != SPLIT_SCHEMA_VERSION:
        raise ValueError("unsupported split schema version")
    if manifest.get("split_file") != split_file.name:
        raise ValueError("split filename does not match manifest")
    if manifest.get("columns") != list(SPLIT_COLUMNS):
        raise ValueError("split columns do not match schema")
    if manifest.get("byte_count") != len(raw):
        raise ValueError("split byte count does not match manifest")
    if manifest.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("split SHA-256 does not match manifest")

    counts = {"train": 0, "validation": 0, "test": 0}
    previous_rank = -1
    previous_event_time: int | None = None
    rank = {"train": 0, "validation": 1, "test": 2}
    with split_file.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != SPLIT_COLUMNS:
            raise ValueError("split CSV columns do not match schema")
        for row in reader:
            name = row["split"]
            if name not in counts or rank[name] < previous_rank:
                raise ValueError("split assignments are invalid or non-chronological")
            previous_rank = rank[name]
            target = int(row["label_target_event_time_ms"])
            event = int(row["event_time_ms"])
            if previous_event_time is not None and event < previous_event_time:
                raise ValueError("split rows are not chronological")
            previous_event_time = event
            train_boundary = manifest["train_boundary_event_time_ms"]
            validation_boundary = manifest["validation_boundary_event_time_ms"]
            if name == "train":
                if event >= train_boundary or target >= train_boundary:
                    raise ValueError("train row violates the validation boundary")
            elif name == "validation":
                if not train_boundary <= event < validation_boundary:
                    raise ValueError("validation row is outside its time interval")
                if target >= validation_boundary:
                    raise ValueError("validation label crosses the test boundary")
            elif event < validation_boundary:
                raise ValueError("test row is before the test boundary")
            counts[name] += 1
    if counts != manifest.get("counts") or sum(counts.values()) != manifest.get("row_count"):
        raise ValueError("split counts do not match manifest")
    if label_path is not None:
        source = verify_labeled_csv(label_path)
        if manifest.get("source_label_sha256") != source.get("sha256"):
            raise ValueError("split dataset does not match the labeled source")
        if manifest.get("source_label_file") != Path(label_path).name:
            raise ValueError("source label filename does not match split manifest")
    return manifest
