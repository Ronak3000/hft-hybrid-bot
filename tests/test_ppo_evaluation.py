from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

try:
    import gymnasium  # noqa: F401

    from engine.market_data import verify_capture
    from engine.research import write_study_plan
    from engine.research.ppo_evaluation import (
        evaluate_ppo_artifacts,
        load_ppo_artifact,
    )
    from tests.test_study_plan import _capture, _plan
except ModuleNotFoundError:
    gymnasium = None


class _LeaveMarketPredictor:
    def predict(self, observation, *, deterministic: bool):
        del observation
        if not deterministic:
            raise AssertionError("evaluation must use deterministic actions")
        return 0, None


@unittest.skipIf(gymnasium is None, "gymnasium is not installed")
class PPOEvaluationTests(unittest.TestCase):
    def _study_and_artifacts(self, root: Path) -> tuple[Path, tuple[Path, ...]]:
        plan = _plan()
        plan_path = root / "study.json"
        write_study_plan(plan, plan_path)
        capture_paths = []
        for index, session in enumerate(plan["sessions"], start=1):
            path = root / plan["capture_directory"] / session["capture_file"]
            _capture(path, index * 100)
            capture_paths.append(path)

        training_path = capture_paths[0]
        config = {
            "tick_size": "0.5",
            "quantity": "1",
            "initial_cash": "1000",
            "maker_fee_rate": "0",
            "order_latency_ns": 0,
            "cancel_latency_ns": 0,
            "max_abs_inventory": "10",
            "maximum_half_spread_ticks": 2,
            "maximum_absolute_skew_ticks": 1,
            "reward_scale": "1",
            "inventory_penalty_per_second": "0",
        }
        metadata_paths = []
        for seed in (7, 19):
            model_path = root / f"model-{seed}.zip"
            model_bytes = f"fake-model-{seed}".encode()
            model_path.write_bytes(model_bytes)
            sidecar = {
                "ppo_artifact_schema_version": 1,
                "environment": "ApexHFTQueueReplay-v0",
                "seed": seed,
                "held_out_splits_used": [],
                "study_plan_sha256": hashlib.sha256(
                    plan_path.read_bytes()
                ).hexdigest(),
                "training_captures": [
                    {
                        "capture_file": training_path.name,
                        "sha256": verify_capture(training_path)["sha256"],
                    }
                ],
                "model_byte_count": len(model_bytes),
                "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
                "configuration": config,
            }
            metadata_path = model_path.with_suffix(".json")
            metadata_path.write_text(json.dumps(sidecar), encoding="utf-8")
            metadata_paths.append(metadata_path)
        return plan_path, tuple(metadata_paths)

    def test_validation_evaluation_is_source_linked_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, artifacts = self._study_and_artifacts(root)
            arguments = dict(
                project_root=root,
                predictor_loader=lambda _: _LeaveMarketPredictor(),
            )
            first = evaluate_ppo_artifacts(
                plan_path, "validation", artifacts, **arguments
            )
            second = evaluate_ppo_artifacts(
                plan_path, "validation", artifacts, **arguments
            )

        self.assertEqual(first, second)
        self.assertEqual(first["model_count"], 2)
        self.assertEqual(first["session_count"], 1)
        self.assertEqual(first["split"], "validation")
        self.assertEqual(first["models"][0]["sessions"][0]["net_pnl"], "0")
        self.assertIsNone(
            first["net_pnl_across_sessions"]["bootstrap_95_percent_lower"]
        )

    def test_test_split_requires_confirmation_and_validated_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, artifacts = self._study_and_artifacts(root)
            with self.assertRaisesRegex(ValueError, "final-test confirmation"):
                evaluate_ppo_artifacts(
                    plan_path,
                    "test",
                    artifacts,
                    project_root=root,
                    predictor_loader=lambda _: _LeaveMarketPredictor(),
                )
            report = evaluate_ppo_artifacts(
                plan_path,
                "test",
                artifacts,
                project_root=root,
                predictor_loader=lambda _: _LeaveMarketPredictor(),
                allow_test=True,
            )

        self.assertTrue(report["test_confirmation_recorded"])
        self.assertEqual(report["claim_status"].split(";")[0], "held-out test result")

    def test_artifact_tampering_and_duplicate_seeds_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, artifacts = self._study_and_artifacts(root)
            training_path = next(
                (root / "captures" / "btcusdt-study").glob("*train*.jsonl")
            )
            artifacts[0].with_suffix(".zip").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "byte count"):
                load_ppo_artifact(
                    artifacts[0],
                    plan_path=plan_path,
                    training_paths=(training_path,),
                )

            first = json.loads(artifacts[0].read_text(encoding="utf-8"))
            second = json.loads(artifacts[1].read_text(encoding="utf-8"))
            first_model = artifacts[0].with_suffix(".zip")
            first["model_byte_count"] = first_model.stat().st_size
            first["model_sha256"] = hashlib.sha256(
                first_model.read_bytes()
            ).hexdigest()
            first["seed"] = second["seed"]
            artifacts[0].write_text(json.dumps(first), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unique training seeds"):
                evaluate_ppo_artifacts(
                    plan_path,
                    "validation",
                    artifacts,
                    project_root=root,
                    predictor_loader=lambda _: _LeaveMarketPredictor(),
                )


if __name__ == "__main__":
    unittest.main()
