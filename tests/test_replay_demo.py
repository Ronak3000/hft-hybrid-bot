from __future__ import annotations

import tempfile
import json
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

try:
    from engine.research.replay_demo import build_replay_segment, export_training_demo
    from engine.simulation import SimulationConfig
    from tests.test_queue_replay_env import _capture, _multisegment_capture
    from tests import test_ppo_evaluation
except ModuleNotFoundError:
    build_replay_segment = None


@unittest.skipIf(build_replay_segment is None, "Gymnasium is not installed")
class ReplayDemoTests(unittest.TestCase):
    def test_explicit_overlay_preserves_source_artifact_and_labels_replay(self):
        class Predictor:
            def predict(self, observation, *, deterministic):
                return 0, None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, artifacts = test_ppo_evaluation.PPOEvaluationTests()._study_and_artifacts(root)
            metadata = artifacts[0]
            artifact = json.loads(metadata.read_text())
            artifact["total_timesteps"] = 64
            metadata.write_text(json.dumps(artifact))
            original_metadata = metadata.read_bytes()
            original_model = metadata.with_suffix(".zip").read_bytes()
            catalog = export_training_demo(plan, root, root / "guarded",
                ppo_metadata=metadata, predictor_loader=lambda path: Predictor(), entry_fee_buffer_bps=Decimal("0"))
            self.assertEqual(metadata.read_bytes(), original_metadata)
            self.assertEqual(metadata.with_suffix(".zip").read_bytes(), original_model)
            self.assertFalse(catalog["model"]["policy_overlay"]["trained_with_overlay"])
            for entry in catalog["sessions"][0]["runs"]:
                run = json.loads((root / "guarded" / entry["file"]).read_text())
                self.assertEqual(run["configuration"]["entry_fee_buffer_bps"], "0")
                if entry["policy"] == "ppo":
                    self.assertIn("fee guard", entry["label"])
            with self.assertRaisesRegex(ValueError, "non-negative"):
                export_training_demo(plan, root, root / "invalid", ppo_metadata=metadata,
                    predictor_loader=lambda path: Predictor(), entry_fee_buffer_bps=Decimal("-1"))

    def test_ppo_decisions_and_accounting_use_the_environment_step(self):
        class Predictor:
            calls = 0

            def predict(self, observation, *, deterministic):
                self.calls += 1
                self.observation_shape = observation.shape
                if not deterministic:
                    raise AssertionError("demo inference must be deterministic")
                return [1, 0, 1], None

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            predictor = Predictor()
            run = build_replay_segment(
                path, "ppo", 0, tick_size=Decimal("0.5"), quantity=Decimal("1"),
                config=SimulationConfig(initial_cash=Decimal("1000"), maker_fee_rate=Decimal("0.01")),
                decision_interval_ns=0, sample_interval_ns=1, predictor=predictor,
                model_configuration={"maximum_half_spread_ticks": 2, "maximum_absolute_skew_ticks": 1, "action_schema_version": 2},
                model_provenance={"seed": 7, "model_sha256": "fixture"},
            )
        self.assertEqual(predictor.observation_shape, (14,))
        self.assertEqual(predictor.calls, run["summary"]["decision_steps"])
        self.assertEqual(run["policy"]["kind"], "Trained PPO")
        self.assertIsNone(run["frames"][0]["decision"])
        self.assertEqual(run["frames"][-1]["decision"], {"quote": True, "half_spread_ticks": 1, "skew_ticks": 0})
        self.assertGreater(run["summary"]["fill_count"], 0)
        self.assertGreater(Decimal(run["summary"]["fees"]), 0)

    def test_export_validates_artifact_and_shares_frozen_costs_with_controls(self):
        class Predictor:
            def predict(self, observation, *, deterministic):
                return [0, 0, 0], None

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, artifacts = test_ppo_evaluation.PPOEvaluationTests()._study_and_artifacts(root)
            metadata = artifacts[0]
            artifact = json.loads(metadata.read_text())
            artifact["configuration"]["action_schema_version"] = 2
            artifact["configuration"]["decision_interval_ns"] = 4
            artifact["total_timesteps"] = 64
            metadata.write_text(json.dumps(artifact))
            calls = []
            def load(path):
                calls.append(path)
                return Predictor()
            catalog = export_training_demo(plan, root, root / "replays", ppo_metadata=metadata, predictor_loader=load)
            self.assertEqual(calls, [metadata.with_suffix(".zip")])
            self.assertEqual(catalog["held_out_splits_used"], [])
            self.assertEqual(catalog["model"]["seed"], 7)
            self.assertEqual(catalog["model"]["total_timesteps"], 64)
            self.assertEqual({run["policy"] for run in catalog["sessions"][0]["runs"]}, {"ppo", "fixed_spread", "inventory_skew", "no_quote", "widest_fixed"})
            for entry in catalog["sessions"][0]["runs"]:
                run = json.loads((root / "replays" / entry["file"]).read_text())
                self.assertEqual(run["configuration"]["decision_interval_ns"], 4)
                self.assertEqual(run["configuration"]["initial_cash"], "1000")
            metadata.with_suffix(".zip").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "byte count"):
                export_training_demo(plan, root, root / "replays", ppo_metadata=metadata, predictor_loader=load)
            self.assertEqual(len(calls), 1)

    def test_displayed_accounting_and_fill_cursor_match_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            args = dict(tick_size=Decimal("0.5"), quantity=Decimal("1"),
                        config=SimulationConfig(initial_cash=Decimal("1000"), maker_fee_rate=Decimal("0.01")),
                        half_spread_ticks=1, decision_interval_ns=0, sample_interval_ns=1)
            run = build_replay_segment(path, "fixed_spread", 0, **args)
            self.assertEqual(run, build_replay_segment(path, "fixed_spread", 0, **args))
            self.assertGreater(len(run["fills"]), 0)
            for frame in run["frames"]:
                self.assertEqual(frame["fill_count"], sum(f["elapsed_ms"] <= frame["elapsed_ms"] for f in run["fills"]))
                with localcontext() as context:
                    context.prec = 50
                    expected = Decimal(frame["cash"]) + Decimal(frame["inventory"]) * Decimal(frame["mid"]) - Decimal("1000")
                self.assertEqual(Decimal(frame["pnl"]), expected)
            self.assertEqual(run["summary"]["fill_count"], len(run["fills"]))

    def test_no_quote_and_explicit_reconnect_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "segments.jsonl"
            _multisegment_capture(path)
            for segment in (0, 1):
                run = build_replay_segment(path, "no_quote", segment,
                    tick_size=Decimal("0.5"), quantity=Decimal("1"), config=SimulationConfig())
                self.assertEqual(run["source"]["segment_index"], segment)
                self.assertEqual(run["source"]["segment_count"], 2)
                self.assertEqual(Decimal(run["summary"]["pnl"]), 0)
                self.assertEqual(run["fills"], [])
                self.assertEqual(run["frames"][0]["elapsed_ms"], 0)


if __name__ == "__main__":
    unittest.main()
