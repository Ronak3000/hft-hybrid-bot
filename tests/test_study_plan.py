from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine.market_data import CaptureWriter
from engine.research import (
    audit_study,
    create_study_plan,
    load_study_plan,
    planned_capture_path,
    validated_split_capture_paths,
    write_study_plan,
)


def _plan_arguments(*, events_per_session: int = 1) -> dict:
    return {
        "study_name": "btcusdt-study",
        "symbol": "BTCUSDT",
        "capture_directory": "captures/btcusdt-study",
        "training_sessions": 1,
        "validation_sessions": 1,
        "test_sessions": 1,
        "events_per_session": events_per_session,
        "depth_limit": 1000,
        "max_reconnects": 2,
        "min_trades_per_session": 1,
        "max_depth_gaps_per_session": 0,
        "max_trade_gaps_per_session": 0,
        "max_disconnects_per_session": 0,
        "created_at_utc": "2026-09-06T00:00:00+00:00",
    }


def _plan(*, events_per_session: int = 1) -> dict:
    return create_study_plan(**_plan_arguments(events_per_session=events_per_session))


def _capture(
    path: Path,
    start_ns: int,
    *,
    snapshot_received_ns: int | None = None,
    trade_received_ns: int | None = None,
) -> None:
    metadata = {
        "captured_at_utc": "2026-09-06T00:00:00+00:00",
        "depth_limit": 1000,
        "source": "test",
        "streams": ["btcusdt@depth@100ms", "btcusdt@trade"],
        "symbol": "BTCUSDT",
        "venue": "binance_spot",
    }
    with CaptureWriter(path, metadata) as writer:
        writer.write(
            "snapshot",
            {
                "lastUpdateId": 100,
                "bids": [["100", "5"]],
                "asks": [["102", "5"]],
            },
            snapshot_received_ns if snapshot_received_ns is not None else start_ns,
        )
        writer.write(
            "delta",
            {
                "e": "depthUpdate",
                "E": start_ns // 1_000_000,
                "s": "BTCUSDT",
                "U": 101,
                "u": 101,
                "b": [],
                "a": [],
            },
            start_ns + 1,
        )
        writer.write(
            "trade",
            {
                "e": "trade",
                "E": start_ns // 1_000_000,
                "s": "BTCUSDT",
                "t": 1,
                "p": "101",
                "q": "1",
                "T": start_ns // 1_000_000,
                "m": True,
            },
            trade_received_ns if trade_received_ns is not None else start_ns + 2,
        )


class StudyPlanTests(unittest.TestCase):
    def test_plan_is_sealed_deterministic_and_path_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "study.json"
            first = _plan()
            second = _plan()
            write_study_plan(first, path)

            self.assertEqual(first, second)
            self.assertEqual(load_study_plan(path), first)
            self.assertEqual(
                planned_capture_path(first, "validation-001", root),
                root
                / "captures"
                / "btcusdt-study"
                / "btcusdt-study-validation-001.jsonl",
            )
            with self.assertRaisesRegex(ValueError, "unknown study session"):
                planned_capture_path(first, "test-999", root)

            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "byte count"):
                load_study_plan(path)

        with self.assertRaisesRegex(ValueError, "inside the project"):
            create_study_plan(
                **{
                    **_plan_arguments(),
                    "capture_directory": "../outside",
                }
            )

    def test_complete_chronological_study_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan()
            plan_path = root / "study.json"
            write_study_plan(plan, plan_path)
            for index, session in enumerate(plan["sessions"], start=1):
                path = root / plan["capture_directory"] / session["capture_file"]
                _capture(path, index * 100)

            first = audit_study(plan_path, project_root=root)
            second = audit_study(plan_path, project_root=root)
            training_paths = validated_split_capture_paths(
                plan_path, "train", project_root=root
            )

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "pass")
        self.assertEqual(first["valid_sessions"], 3)
        self.assertFalse(first["issues"])
        self.assertEqual(
            first["sessions"][0]["summary"]["receive_timestamp_regressions"], 0
        )
        self.assertEqual(
            first["valid_capture_files_by_split"]["validation"],
            ["btcusdt-study-validation-001.jsonl"],
        )
        self.assertEqual(
            [item["split"] for item in first["sessions"]],
            ["train", "validation", "test"],
        )
        self.assertEqual(
            [path.name for path in training_paths],
            ["btcusdt-study-train-001.jsonl"],
        )

    def test_missing_capture_is_reported_as_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan()
            plan_path = root / "study.json"
            write_study_plan(plan, plan_path)
            first = plan["sessions"][0]
            _capture(
                root / plan["capture_directory"] / first["capture_file"], 100
            )
            report = audit_study(plan_path, project_root=root)
            training_paths = validated_split_capture_paths(
                plan_path, "train", project_root=root
            )
            with self.assertRaisesRegex(
                ValueError, "validation split is incomplete"
            ):
                validated_split_capture_paths(
                    plan_path, "validation", project_root=root
                )

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["valid_sessions"], 1)
        self.assertEqual(report["missing_sessions"], 2)
        self.assertEqual(
            [path.name for path in training_paths],
            ["btcusdt-study-train-001.jsonl"],
        )

    def test_training_split_does_not_open_later_capture_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan()
            plan_path = root / "study.json"
            write_study_plan(plan, plan_path)
            paths = []
            for index, session in enumerate(plan["sessions"], start=1):
                path = root / plan["capture_directory"] / session["capture_file"]
                _capture(path, index * 100)
                paths.append(path)
            paths[1].write_bytes(paths[1].read_bytes() + b"tampered")

            training_paths = validated_split_capture_paths(
                plan_path, "train", project_root=root
            )
            with self.assertRaisesRegex(ValueError, "invalid capture"):
                validated_split_capture_paths(
                    plan_path, "validation", project_root=root
                )

        self.assertEqual(training_paths, (paths[0],))

    def test_snapshot_buffer_boundary_is_not_a_stream_timestamp_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan()
            plan_path = root / "study.json"
            write_study_plan(plan, plan_path)
            first = plan["sessions"][0]
            _capture(
                root / plan["capture_directory"] / first["capture_file"],
                100,
                snapshot_received_ns=150,
            )
            report = audit_study(plan_path, project_root=root)

        first_report = report["sessions"][0]
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(first_report["status"], "valid")
        self.assertEqual(
            first_report["summary"]["receive_timestamp_regressions"], 0
        )

    def test_actual_stream_timestamp_regression_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan()
            plan_path = root / "study.json"
            write_study_plan(plan, plan_path)
            first = plan["sessions"][0]
            _capture(
                root / plan["capture_directory"] / first["capture_file"],
                100,
                trade_received_ns=100,
            )
            report = audit_study(plan_path, project_root=root)

        self.assertEqual(report["status"], "fail")
        self.assertIn(
            "receive_timestamp_regressions",
            {issue["code"] for issue in report["issues"]},
        )

    def test_duplicate_and_overlapping_sessions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan()
            plan_path = root / "study.json"
            write_study_plan(plan, plan_path)
            for session in plan["sessions"]:
                path = root / plan["capture_directory"] / session["capture_file"]
                _capture(path, 100)
            report = audit_study(plan_path, project_root=root)

        codes = {issue["code"] for issue in report["issues"]}
        self.assertEqual(report["status"], "fail")
        self.assertIn("duplicate_capture_content", codes)
        self.assertIn("session_not_strictly_after_previous_session", codes)

    def test_predeclared_quality_shortfall_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(events_per_session=2)
            plan_path = root / "study.json"
            write_study_plan(plan, plan_path)
            for index, session in enumerate(plan["sessions"], start=1):
                path = root / plan["capture_directory"] / session["capture_file"]
                _capture(path, index * 100)
            report = audit_study(plan_path, project_root=root)

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["rejected_sessions"], 3)
        self.assertTrue(
            all(
                issue["code"] == "insufficient_applied_depth_deltas"
                for issue in report["issues"]
            )
        )


if __name__ == "__main__":
    unittest.main()
