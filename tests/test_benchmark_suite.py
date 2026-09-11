from __future__ import annotations

import unittest

from scripts.run_engine_benchmark_suite import summarize_runs


def _run(mean: float, p50: float, p99: float, p99_9: float) -> dict:
    return {
        "name": "benchmark",
        "measurement": "batched",
        "compiler": {"name": "test"},
        "build": {"mode": "release"},
        "rng_seed": 42,
        "warmup_actions": 10,
        "measured_actions": 100,
        "batch_size": 10,
        "batch_samples": 10,
        "latency_ns_per_action": {
            "mean": mean,
            "p50": p50,
            "p99": p99,
            "p99_9": p99_9,
        },
        "observed_actions_per_second": 1_000_000_000 / mean,
        "outcomes": {"successful_crosses": 10},
        "state_checksum": 123,
    }


class BenchmarkSuiteTests(unittest.TestCase):
    def test_summary_uses_process_median_and_retains_range(self) -> None:
        report = summarize_runs(
            [_run(10, 8, 20, 30), _run(12, 9, 25, 40), _run(11, 7, 22, 35)]
        )

        self.assertEqual(report["process_runs"], 3)
        self.assertEqual(
            report["latency_ns_per_action"]["mean"],
            {"minimum": 10.0, "median": 11.0, "maximum": 12.0},
        )
        self.assertEqual(report["latency_ns_per_action"]["p99"]["median"], 22)

    def test_summary_rejects_changed_workload_outcomes(self) -> None:
        first = _run(10, 8, 20, 30)
        second = _run(11, 9, 21, 31)
        second["state_checksum"] = 999

        with self.assertRaisesRegex(RuntimeError, "state_checksum changed"):
            summarize_runs([first, second])


if __name__ == "__main__":
    unittest.main()
