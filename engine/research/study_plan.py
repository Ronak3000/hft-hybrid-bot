"""Immutable study plans and deterministic multi-session capture audits."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.market_data import replay_capture, verify_capture


STUDY_PLAN_SCHEMA_VERSION = 1
STUDY_AUDIT_SCHEMA_VERSION = 1
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SPLITS = ("train", "validation", "test")


def create_study_plan(
    *,
    study_name: str,
    symbol: str,
    capture_directory: str,
    training_sessions: int,
    validation_sessions: int,
    test_sessions: int,
    events_per_session: int,
    depth_limit: int,
    max_reconnects: int,
    min_trades_per_session: int,
    max_depth_gaps_per_session: int,
    max_trade_gaps_per_session: int,
    max_disconnects_per_session: int,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    name = _study_identifier(study_name)
    normalized_symbol = _symbol(symbol)
    directory = _relative_directory(capture_directory)
    split_counts = {
        "train": _positive_int(training_sessions, "training_sessions"),
        "validation": _positive_int(validation_sessions, "validation_sessions"),
        "test": _positive_int(test_sessions, "test_sessions"),
    }
    events = _positive_int(events_per_session, "events_per_session")
    if depth_limit not in {100, 500, 1000, 5000}:
        raise ValueError("depth_limit must be one of 100, 500, 1000, or 5000")
    reconnects = _nonnegative_int(max_reconnects, "max_reconnects")
    minimum_trades = _nonnegative_int(
        min_trades_per_session, "min_trades_per_session"
    )
    maximum_depth_gaps = _nonnegative_int(
        max_depth_gaps_per_session, "max_depth_gaps_per_session"
    )
    maximum_trade_gaps = _nonnegative_int(
        max_trade_gaps_per_session, "max_trade_gaps_per_session"
    )
    maximum_disconnects = _nonnegative_int(
        max_disconnects_per_session, "max_disconnects_per_session"
    )
    created = _utc_timestamp(created_at_utc)

    sessions: list[dict[str, Any]] = []
    ordinal = 0
    for split in _SPLITS:
        for split_index in range(1, split_counts[split] + 1):
            ordinal += 1
            session_id = f"{split}-{split_index:03d}"
            sessions.append(
                {
                    "capture_file": f"{name}-{session_id}.jsonl",
                    "ordinal": ordinal,
                    "session_id": session_id,
                    "split": split,
                }
            )

    return {
        "study_plan_schema_version": STUDY_PLAN_SCHEMA_VERSION,
        "study_name": name,
        "created_at_utc": created,
        "split_policy": (
            "chronological_non_overlapping_train_then_validation_then_test"
        ),
        "capture_directory": directory,
        "capture_configuration": {
            "venue": "binance_spot",
            "symbol": normalized_symbol,
            "events_per_session": events,
            "depth_limit": depth_limit,
            "max_reconnects": reconnects,
        },
        "quality_thresholds": {
            "min_applied_depth_deltas": events,
            "min_accepted_trades": minimum_trades,
            "max_depth_sequence_gaps": maximum_depth_gaps,
            "max_trade_id_gaps": maximum_trade_gaps,
            "max_disconnects": maximum_disconnects,
            "require_final_synchronized_book": True,
            "require_nondecreasing_receive_timestamps": True,
            "require_zero_duplicate_trades": True,
            "require_zero_out_of_order_trades": True,
        },
        "split_counts": split_counts,
        "sessions": sessions,
    }


def write_study_plan(plan: Mapping[str, Any], output_path: str | Path) -> Path:
    _validate_plan(plan)
    output = Path(output_path)
    manifest_path = Path(f"{output}.manifest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        raise FileExistsError(f"study-plan manifest already exists: {manifest_path}")
    encoded = (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with output.open("xb") as destination:
        destination.write(encoded)
        destination.flush()
        os.fsync(destination.fileno())
    manifest = {
        "byte_count": len(encoded),
        "plan_file": output.name,
        "schema_version": STUDY_PLAN_SCHEMA_VERSION,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
    with manifest_path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        destination.flush()
        os.fsync(destination.fileno())
    return output


def load_study_plan(path: str | Path) -> Mapping[str, Any]:
    plan_path = Path(path)
    manifest_path = Path(f"{plan_path}.manifest.json")
    try:
        raw = plan_path.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        plan = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read study plan: {exc}") from exc
    if manifest.get("schema_version") != STUDY_PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported study-plan manifest schema version")
    if manifest.get("plan_file") != plan_path.name:
        raise ValueError("study-plan manifest filename does not match")
    if manifest.get("byte_count") != len(raw):
        raise ValueError("study-plan byte count does not match manifest")
    if manifest.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("study-plan SHA-256 does not match manifest")
    _validate_plan(plan)
    return plan


def planned_capture_path(
    plan: Mapping[str, Any], session_id: str, project_root: str | Path
) -> Path:
    _validate_plan(plan)
    matching = [item for item in plan["sessions"] if item["session_id"] == session_id]
    if not matching:
        raise ValueError(f"unknown study session: {session_id}")
    return Path(project_root) / plan["capture_directory"] / matching[0]["capture_file"]


def validated_split_capture_paths(
    plan_path: str | Path,
    split: str,
    *,
    project_root: str | Path,
) -> tuple[Path, ...]:
    """Return one complete valid split without admitting another split's data."""
    if split not in _SPLITS:
        raise ValueError(f"split must be one of: {', '.join(_SPLITS)}")
    plan = load_study_plan(plan_path)
    audit = audit_study(
        plan_path, project_root=project_root, through_split=split
    )
    if audit["status"] == "fail":
        raise ValueError("study contains rejected or invalid capture data")
    selected = [item for item in audit["sessions"] if item["split"] == split]
    incomplete = [item["session_id"] for item in selected if item["status"] != "valid"]
    if incomplete:
        raise ValueError(
            f"{split} split is incomplete: {', '.join(incomplete)}"
        )
    if audit["status"] != "pass":
        raise ValueError(f"study is incomplete through the {split} split")
    root = Path(project_root)
    return tuple(
        root / plan["capture_directory"] / item["capture_file"]
        for item in selected
    )


def audit_study(
    plan_path: str | Path,
    *,
    project_root: str | Path,
    through_split: str | None = None,
) -> dict[str, Any]:
    plan_file = Path(plan_path)
    plan = load_study_plan(plan_file)
    plan_hash = hashlib.sha256(plan_file.read_bytes()).hexdigest()
    root = Path(project_root)
    thresholds = plan["quality_thresholds"]
    configuration = plan["capture_configuration"]
    sessions: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    capture_hashes: set[str] = set()
    previous_end_ns: int | None = None

    if through_split is not None and through_split not in _SPLITS:
        raise ValueError(f"through_split must be one of: {', '.join(_SPLITS)}")
    included_splits = (
        _SPLITS
        if through_split is None
        else _SPLITS[: _SPLITS.index(through_split) + 1]
    )

    for expected in plan["sessions"]:
        if expected["split"] not in included_splits:
            continue
        capture_path = (
            root / plan["capture_directory"] / expected["capture_file"]
        )
        if not capture_path.exists():
            sessions.append({**expected, "status": "missing"})
            issues.append(
                {
                    "code": "missing_capture",
                    "session_id": expected["session_id"],
                    "message": f"missing capture: {expected['capture_file']}",
                }
            )
            continue
        try:
            summary = _capture_summary(capture_path)
        except (OSError, ValueError) as exc:
            sessions.append({**expected, "status": "invalid", "error": str(exc)})
            issues.append(
                {
                    "code": "invalid_capture",
                    "session_id": expected["session_id"],
                    "message": str(exc),
                }
            )
            continue

        session_issues: list[str] = []
        if summary["capture_sha256"] in capture_hashes:
            session_issues.append("duplicate_capture_content")
        capture_hashes.add(summary["capture_sha256"])
        metadata = summary["capture_metadata"]
        if metadata.get("venue") != configuration["venue"]:
            session_issues.append("venue_mismatch")
        if metadata.get("symbol") != configuration["symbol"]:
            session_issues.append("symbol_mismatch")
        if metadata.get("depth_limit") != configuration["depth_limit"]:
            session_issues.append("depth_limit_mismatch")
        if summary["applied_depth_deltas"] < thresholds["min_applied_depth_deltas"]:
            session_issues.append("insufficient_applied_depth_deltas")
        if summary["accepted_trades"] < thresholds["min_accepted_trades"]:
            session_issues.append("insufficient_accepted_trades")
        if summary["depth_sequence_gaps"] > thresholds["max_depth_sequence_gaps"]:
            session_issues.append("too_many_depth_sequence_gaps")
        if summary["trade_id_gaps"] > thresholds["max_trade_id_gaps"]:
            session_issues.append("too_many_trade_id_gaps")
        if summary["disconnects"] > thresholds["max_disconnects"]:
            session_issues.append("too_many_disconnects")
        if thresholds["require_final_synchronized_book"] and not summary[
            "final_book_synchronized"
        ]:
            session_issues.append("final_book_not_synchronized")
        if thresholds["require_nondecreasing_receive_timestamps"] and summary[
            "receive_timestamp_regressions"
        ]:
            session_issues.append("receive_timestamp_regressions")
        if thresholds["require_zero_duplicate_trades"] and summary[
            "duplicate_trades"
        ]:
            session_issues.append("duplicate_trades")
        if thresholds["require_zero_out_of_order_trades"] and summary[
            "out_of_order_trades"
        ]:
            session_issues.append("out_of_order_trades")
        if (
            previous_end_ns is not None
            and summary["start_received_time_ns"] <= previous_end_ns
        ):
            session_issues.append("session_not_strictly_after_previous_session")
        previous_end_ns = max(previous_end_ns or 0, summary["end_received_time_ns"])

        status = "valid" if not session_issues else "rejected"
        sessions.append({**expected, "status": status, "summary": summary})
        for code in session_issues:
            issues.append(
                {
                    "code": code,
                    "session_id": expected["session_id"],
                    "message": code.replace("_", " "),
                }
            )

    valid_sessions = sum(item["status"] == "valid" for item in sessions)
    missing_sessions = sum(item["status"] == "missing" for item in sessions)
    rejected_sessions = len(sessions) - valid_sessions - missing_sessions
    status = "pass"
    if rejected_sessions:
        status = "fail"
    elif missing_sessions:
        status = "incomplete"
    valid_capture_files_by_split = {
        split: [
            item["capture_file"]
            for item in sessions
            if item["split"] == split and item["status"] == "valid"
        ]
        for split in _SPLITS
    }
    return {
        "study_audit_schema_version": STUDY_AUDIT_SCHEMA_VERSION,
        "study_plan_file": plan_file.name,
        "study_plan_sha256": plan_hash,
        "study_name": plan["study_name"],
        "capture_directory": plan["capture_directory"],
        "status": status,
        "planned_sessions": len(sessions),
        "valid_sessions": valid_sessions,
        "missing_sessions": missing_sessions,
        "rejected_sessions": rejected_sessions,
        "valid_capture_files_by_split": valid_capture_files_by_split,
        "sessions": sessions,
        "issues": issues,
    }


def _capture_summary(path: Path) -> dict[str, Any]:
    manifest = verify_capture(path)
    replay = replay_capture(path)
    kinds: dict[str, int] = {}
    timestamps: list[int] = []
    timestamp_regressions = 0
    previous_stream_timestamp: int | None = None
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            kind = record["kind"]
            kinds[kind] = kinds.get(kind, 0) + 1
            if kind != "metadata":
                received = record["received_time_ns"]
                timestamps.append(received)
                # A REST snapshot is intentionally serialized before the
                # WebSocket messages buffered while it was in flight. Its
                # receive timestamp can therefore exceed the first buffered
                # event without violating stream arrival order.
                if kind != "snapshot":
                    if (
                        previous_stream_timestamp is not None
                        and received < previous_stream_timestamp
                    ):
                        timestamp_regressions += 1
                    previous_stream_timestamp = received
    if not timestamps:
        raise ValueError("capture contains no timestamped market-data records")
    start = min(timestamps)
    end = max(timestamps)
    return {
        "capture_sha256": manifest["sha256"],
        "capture_metadata": manifest["metadata"],
        "record_count": manifest["record_count"],
        "start_received_time_ns": start,
        "end_received_time_ns": end,
        "duration_ns": end - start,
        "receive_timestamp_regressions": timestamp_regressions,
        "snapshots": replay.snapshots,
        "applied_depth_deltas": replay.applied_deltas,
        "stale_depth_deltas": replay.stale_deltas,
        "depth_sequence_gaps": replay.gaps,
        "accepted_trades": replay.accepted_trades,
        "duplicate_trades": replay.duplicate_trades,
        "out_of_order_trades": replay.out_of_order_trades,
        "trade_id_gaps": replay.trade_id_gaps,
        "disconnects": kinds.get("disconnect", 0),
        "final_book_synchronized": replay.book.synchronized,
    }


def _validate_plan(plan: Mapping[str, Any]) -> None:
    if not isinstance(plan, Mapping):
        raise ValueError("study plan must be an object")
    if plan.get("study_plan_schema_version") != STUDY_PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported study-plan schema version")
    configuration = plan.get("capture_configuration")
    thresholds = plan.get("quality_thresholds")
    split_counts = plan.get("split_counts")
    if not all(
        isinstance(item, Mapping)
        for item in (configuration, thresholds, split_counts)
    ):
        raise ValueError("study plan configuration sections must be objects")
    expected = create_study_plan(
        study_name=plan.get("study_name"),
        symbol=configuration.get("symbol"),
        capture_directory=plan.get("capture_directory"),
        training_sessions=split_counts.get("train"),
        validation_sessions=split_counts.get("validation"),
        test_sessions=split_counts.get("test"),
        events_per_session=configuration.get("events_per_session"),
        depth_limit=configuration.get("depth_limit"),
        max_reconnects=configuration.get("max_reconnects"),
        min_trades_per_session=thresholds.get("min_accepted_trades"),
        max_depth_gaps_per_session=thresholds.get("max_depth_sequence_gaps"),
        max_trade_gaps_per_session=thresholds.get("max_trade_id_gaps"),
        max_disconnects_per_session=thresholds.get("max_disconnects"),
        created_at_utc=plan.get("created_at_utc"),
    )
    if dict(plan) != expected:
        raise ValueError("study plan contains inconsistent or unsupported fields")


def _study_identifier(value: Any) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError("study_name must use lowercase letters, digits, and hyphens")
    return value


def _symbol(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("symbol must be a non-empty string")
    normalized = value.strip().upper()
    if not normalized.isalnum():
        raise ValueError("symbol must contain only letters and digits")
    return normalized


def _relative_directory(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("capture_directory must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("capture_directory must remain inside the project")
    return path.as_posix().rstrip("/")


def _positive_int(value: Any, field: str) -> int:
    parsed = _nonnegative_int(value, field)
    if parsed == 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _utc_timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if not isinstance(value, str):
        raise ValueError("created_at_utc must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("created_at_utc must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("created_at_utc must use UTC")
    return parsed.isoformat()
