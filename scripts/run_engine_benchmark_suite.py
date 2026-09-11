"""Run repeatable process-level samples of the C++ latency benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


REPORT_SCHEMA_VERSION = 1


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cpu_model() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or "unavailable"


@contextmanager
def _temporary_cpu_affinity(cpu: int | None) -> Iterator[dict[str, Any]]:
    if cpu is None:
        yield {"requested_cpu": None, "applied": False, "method": "not requested"}
        return

    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetProcessAffinityMask.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_size_t),
        )
        kernel32.GetProcessAffinityMask.restype = ctypes.c_int
        kernel32.SetProcessAffinityMask.argtypes = (
            ctypes.c_void_p,
            ctypes.c_size_t,
        )
        kernel32.SetProcessAffinityMask.restype = ctypes.c_int
        process = kernel32.GetCurrentProcess()
        process_mask = ctypes.c_size_t()
        system_mask = ctypes.c_size_t()
        if not kernel32.GetProcessAffinityMask(
            process, ctypes.byref(process_mask), ctypes.byref(system_mask)
        ):
            raise OSError(ctypes.get_last_error(), "GetProcessAffinityMask failed")
        target_mask = 1 << cpu
        if target_mask & system_mask.value == 0:
            raise ValueError(f"CPU {cpu} is not available to this process")
        if not kernel32.SetProcessAffinityMask(process, target_mask):
            raise OSError(ctypes.get_last_error(), "SetProcessAffinityMask failed")
        try:
            yield {
                "requested_cpu": cpu,
                "applied": True,
                "method": "inherited Windows process affinity mask",
            }
        finally:
            if not kernel32.SetProcessAffinityMask(process, process_mask.value):
                raise OSError(
                    ctypes.get_last_error(), "failed to restore process affinity"
                )
        return

    if hasattr(os, "sched_getaffinity") and hasattr(os, "sched_setaffinity"):
        original = os.sched_getaffinity(0)
        if cpu not in original:
            raise ValueError(f"CPU {cpu} is not available to this process")
        os.sched_setaffinity(0, {cpu})
        try:
            yield {
                "requested_cpu": cpu,
                "applied": True,
                "method": "inherited POSIX process affinity",
            }
        finally:
            os.sched_setaffinity(0, original)
        return

    raise RuntimeError("CPU affinity is unsupported on this platform")


def _run_once(command: list[str], timeout_seconds: int) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout_seconds,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("benchmark did not emit valid JSON") from exc
    if result.get("benchmark_schema_version") != 1:
        raise RuntimeError("unsupported benchmark output schema")
    return result


def _assert_comparable(runs: list[dict[str, Any]]) -> None:
    if not runs:
        raise ValueError("at least one benchmark run is required")
    invariant_fields = (
        "name",
        "measurement",
        "compiler",
        "build",
        "rng_seed",
        "warmup_actions",
        "measured_actions",
        "batch_size",
        "batch_samples",
        "outcomes",
        "state_checksum",
    )
    reference = runs[0]
    for run in runs[1:]:
        for field in invariant_fields:
            if run.get(field) != reference.get(field):
                raise RuntimeError(
                    f"benchmark runs are not comparable: {field} changed"
                )


def _distribution(values: list[float]) -> dict[str, float]:
    return {
        "minimum": min(values),
        "median": statistics.median(values),
        "maximum": max(values),
    }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    _assert_comparable(runs)
    latency_keys = ("mean", "p50", "p99", "p99_9")
    return {
        "process_runs": len(runs),
        "latency_ns_per_action": {
            key: _distribution(
                [float(run["latency_ns_per_action"][key]) for run in runs]
            )
            for key in latency_keys
        },
        "observed_actions_per_second": _distribution(
            [float(run["observed_actions_per_second"]) for run in runs]
        ),
        "summary_rule": "median/minimum/maximum across complete process runs",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=_positive_int, default=5)
    parser.add_argument("--cpu", type=_nonnegative_int)
    parser.add_argument("--actions", type=_positive_int, default=1_000_000)
    parser.add_argument("--warmup-actions", type=_positive_int, default=20_000)
    parser.add_argument("--batch-size", type=_positive_int, default=256)
    parser.add_argument("--seed", type=_positive_int, default=42)
    parser.add_argument("--timeout-seconds", type=_positive_int, default=120)
    args = parser.parse_args()

    binary = args.binary.resolve(strict=True)
    if not binary.is_file():
        parser.error("--binary must be a file")
    if args.output.exists():
        parser.error("--output already exists")
    command = [
        str(binary),
        "--actions",
        str(args.actions),
        "--warmup-actions",
        str(args.warmup_actions),
        "--batch-size",
        str(args.batch_size),
        "--seed",
        str(args.seed),
    ]

    try:
        with _temporary_cpu_affinity(args.cpu) as affinity:
            _run_once(command, args.timeout_seconds)  # discarded process warmup
            runs = [
                _run_once(command, args.timeout_seconds) for _ in range(args.runs)
            ]
        report = {
            "benchmark_report_schema_version": REPORT_SCHEMA_VERSION,
            "claim_status": (
                "single-threaded in-process synthetic microbenchmark; "
                "not network or exchange latency"
            ),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "executable": {
                "file": binary.name,
                "byte_count": binary.stat().st_size,
                "sha256": _sha256(binary),
            },
            "host": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "cpu_model": _cpu_model(),
                "logical_cpus": os.cpu_count(),
                "python_version": platform.python_version(),
                "affinity": affinity,
            },
            "parameters": {
                "process_warmup_runs": 1,
                "recorded_runs": args.runs,
                "actions": args.actions,
                "warmup_actions_per_process": args.warmup_actions,
                "batch_size": args.batch_size,
                "seed": args.seed,
            },
            "summary": summarize_runs(runs),
            "runs": runs,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    except (
        OSError,
        RuntimeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        parser.error(str(exc))

    print(f"Recorded process runs: {args.runs}")
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
