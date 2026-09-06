from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HMM_AVAILABLE = bool(importlib.util.find_spec("numpy") and importlib.util.find_spec("hmmlearn"))


@unittest.skipUnless(HMM_AVAILABLE, "optional HMM research dependencies are not installed")
class HMMResearchTests(unittest.TestCase):
    @staticmethod
    def _dataset(path: Path, alter_test: bool = False, alter_labels: bool = False) -> None:
        from engine.research.dataset import SPLIT_COLUMNS, SPLIT_SCHEMA_VERSION

        counts = {"train": 360, "validation": 120, "test": 120}
        with path.open("x", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=SPLIT_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for index in range(600):
                if index < 360:
                    split = "train"
                elif index < 480:
                    split = "validation"
                else:
                    split = "test"
                state = (index // 25) % 2
                noise = ((index % 7) - 3) * 0.01
                imbalance = (-0.8 if state == 0 else 0.8) + noise
                microprice_deviation = imbalance * 0.5
                ofi = imbalance * 2 + ((index % 5) - 2) * 0.02
                if alter_test and split == "test":
                    imbalance += 100
                    microprice_deviation -= 50
                    ofi += 200
                label = imbalance * 0.1
                if alter_labels:
                    label += 1_000
                event_time = index * 100
                row = {
                    "segment_id": 0,
                    "event_time_ms": event_time,
                    "received_time_ns": event_time * 1_000_000 + 7,
                    "update_id": index + 1,
                    "best_bid": 100,
                    "best_ask": 101,
                    "bid_quantity_l1": 10,
                    "ask_quantity_l1": 10,
                    "mid_price": 100.5,
                    "spread": 1,
                    "spread_bps": 1 + state * 0.1 + noise,
                    "microprice": 100.5 + microprice_deviation / 10_000,
                    "microprice_deviation_bps": microprice_deviation,
                    "bid_depth": 50,
                    "ask_depth": 50,
                    "depth_imbalance": imbalance,
                    "ofi_l1": ofi,
                    "bid_levels_changed": 2,
                    "ask_levels_changed": 2,
                    "label_horizon_ms": 50,
                    "label_target_segment_id": 0,
                    "label_target_event_time_ms": event_time + 50,
                    "label_target_update_id": index + 2,
                    "label_realized_horizon_ms": 50,
                    "label_mid_return_bps": label,
                    "split": split,
                }
                writer.writerow(row)

        raw = path.read_bytes()
        manifest = {
            "byte_count": len(raw),
            "columns": list(SPLIT_COLUMNS),
            "counts": counts,
            "purged_boundary_crossing_labels": 0,
            "row_count": 600,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "source_capture_sha256": "synthetic-test-capture",
            "source_feature_sha256": "synthetic-test-features",
            "source_label_file": "synthetic-test-labels.csv",
            "source_label_sha256": "synthetic-test-labels",
            "split_file": path.name,
            "split_schema_version": SPLIT_SCHEMA_VERSION,
            "test_ratio": "0.2",
            "train_boundary_event_time_ms": 36_000,
            "train_ratio": "0.6",
            "validation_boundary_event_time_ms": 48_000,
            "validation_ratio": "0.2",
        }
        Path(f"{path}.manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def test_fit_is_train_scaled_and_exports_causal_probabilities(self) -> None:
        import numpy as np

        from engine.research.hmm_regime import (
            HMMConfig,
            fit_hmm_regimes,
            verify_hmm_artifact,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset.csv"
            artifact = root / "hmm.json"
            predictions = root / "predictions.csv"
            self._dataset(dataset)
            report = fit_hmm_regimes(
                dataset,
                artifact,
                predictions,
                HMMConfig(
                    state_counts=(2, 3),
                    seeds=(7,),
                    n_iter=100,
                    min_samples_per_state=5,
                    min_state_occupancy=0.001,
                ),
            )
            verify_hmm_artifact(artifact, dataset, predictions)
            with predictions.open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))

        self.assertIn(report["selected"]["state_count"], (2, 3))
        self.assertEqual(report["scaler"]["fit_partition"], "train")
        self.assertFalse(report["evaluation_protocol"]["test_used_for_selection"])
        self.assertEqual(report["evaluation_protocol"]["inference"], "forward_filter_only")
        self.assertEqual(len(rows), 600)
        probability_columns = [name for name in rows[0] if name.startswith("regime_probability_")]
        for row in rows[::53]:
            self.assertAlmostEqual(
                sum(float(row[name]) for name in probability_columns), 1.0, places=12
            )
        means = np.asarray(report["model"]["means"])
        self.assertEqual(
            [tuple(row) for row in means], sorted(tuple(row) for row in means)
        )

    def test_future_observations_cannot_change_past_filtered_probabilities(self) -> None:
        import numpy as np

        from engine.research.hmm_regime import forward_filter

        observations = np.asarray([[-1.0], [-0.8], [-1.1], [0.9], [1.0]])
        changed_future = observations.copy()
        changed_future[3:] = -100
        parameters = {
            "lengths": [5],
            "start_probability": np.asarray([0.5, 0.5]),
            "transition_matrix": np.asarray([[0.95, 0.05], [0.05, 0.95]]),
            "means": np.asarray([[-1.0], [1.0]]),
            "diagonal_covariances": np.asarray([[0.2], [0.2]]),
        }
        original = forward_filter(observations=observations, **parameters)
        changed = forward_filter(observations=changed_future, **parameters)
        np.testing.assert_allclose(original[:3], changed[:3], atol=0, rtol=0)

    def test_test_features_and_all_labels_cannot_change_fitted_parameters(self) -> None:
        from engine.research.hmm_regime import HMMConfig, fit_hmm_regimes

        config = HMMConfig(
            state_counts=(2,),
            seeds=(7,),
            n_iter=80,
            min_samples_per_state=5,
            min_state_occupancy=0.001,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.csv"
            altered = root / "altered.csv"
            self._dataset(original)
            self._dataset(altered, alter_test=True, alter_labels=True)
            first = fit_hmm_regimes(
                original, root / "first.json", root / "first-predictions.csv", config
            )
            second = fit_hmm_regimes(
                altered, root / "second.json", root / "second-predictions.csv", config
            )

        self.assertEqual(first["scaler"], second["scaler"])
        self.assertEqual(first["model"], second["model"])
        self.assertEqual(first["selected"], second["selected"])
        self.assertNotEqual(
            first["metrics"]["test"]["log_likelihood_per_row"],
            second["metrics"]["test"]["log_likelihood_per_row"],
        )


if __name__ == "__main__":
    unittest.main()
