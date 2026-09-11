"""Integrity-checked, chronological evaluation for queue-replay PPO artifacts."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from pathlib import Path
from typing import Any, Callable, Protocol

from engine.market_data import verify_capture
from engine.rl_trading.envs import QueueReplayEnv
from engine.simulation import SimulationConfig
from engine.simulation.queue_simulator import SIMULATION_DECIMAL_CONTEXT

from .study_plan import validated_split_capture_paths


PPO_EVALUATION_SCHEMA_VERSION = 1


class Predictor(Protocol):
    def predict(
        self, observation: Any, *, deterministic: bool
    ) -> tuple[Any, Any]: ...


PredictorLoader = Callable[[Path], Predictor]


def load_ppo_artifact(
    metadata_path: str | Path,
    *,
    plan_path: str | Path,
    training_paths: tuple[Path, ...],
) -> tuple[dict[str, Any], Path]:
    """Validate a training sidecar and its model without trusting filenames."""
    sidecar_path = Path(metadata_path)
    try:
        artifact = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read PPO metadata: {sidecar_path.name}") from exc
    if not isinstance(artifact, dict):
        raise ValueError("PPO metadata must be a JSON object")
    if artifact.get("ppo_artifact_schema_version") != 1:
        raise ValueError("unsupported PPO artifact schema version")
    if artifact.get("environment") != "ApexHFTQueueReplay-v0":
        raise ValueError("PPO artifact uses a different environment")
    seed = artifact.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("PPO artifact seed must be a non-negative integer")
    if artifact.get("held_out_splits_used") != []:
        raise ValueError("PPO artifact is not training-split-only")

    plan = Path(plan_path)
    plan_bytes = plan.read_bytes()
    if artifact.get("study_plan_sha256") != hashlib.sha256(plan_bytes).hexdigest():
        raise ValueError("PPO artifact study-plan hash does not match")
    expected_sources = [
        {"capture_file": path.name, "sha256": verify_capture(path)["sha256"]}
        for path in training_paths
    ]
    if artifact.get("training_captures") != expected_sources:
        raise ValueError("PPO artifact training captures do not match the plan")

    model_path = sidecar_path.with_suffix(".zip")
    try:
        model_bytes = model_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read PPO model: {model_path.name}") from exc
    if artifact.get("model_byte_count") != len(model_bytes):
        raise ValueError("PPO model byte count does not match its metadata")
    if artifact.get("model_sha256") != hashlib.sha256(model_bytes).hexdigest():
        raise ValueError("PPO model SHA-256 does not match its metadata")
    if not isinstance(artifact.get("configuration"), dict):
        raise ValueError("PPO artifact has no configuration object")
    required_configuration = {
        "tick_size",
        "quantity",
        "initial_cash",
        "maker_fee_rate",
        "order_latency_ns",
        "cancel_latency_ns",
        "max_abs_inventory",
        "maximum_half_spread_ticks",
        "maximum_absolute_skew_ticks",
        "reward_scale",
        "inventory_penalty_per_second",
    }
    missing = required_configuration - artifact["configuration"].keys()
    if missing:
        raise ValueError(
            "PPO artifact configuration is missing: " + ", ".join(sorted(missing))
        )
    return artifact, model_path


def evaluate_ppo_artifacts(
    plan_path: str | Path,
    split: str,
    metadata_paths: tuple[str | Path, ...],
    *,
    project_root: str | Path,
    predictor_loader: PredictorLoader,
    allow_test: bool = False,
    bootstrap_seed: int = 17,
    bootstrap_samples: int = 2000,
) -> dict[str, Any]:
    """Evaluate unique PPO seeds on a complete validation or test split."""
    if split not in {"validation", "test"}:
        raise ValueError("PPO evaluation split must be validation or test")
    if split == "test" and not allow_test:
        raise ValueError("test evaluation requires explicit final-test confirmation")
    if len(metadata_paths) < 2:
        raise ValueError("at least two independently seeded PPO artifacts are required")
    if isinstance(bootstrap_seed, bool) or not isinstance(bootstrap_seed, int):
        raise ValueError("bootstrap_seed must be an integer")
    if (
        isinstance(bootstrap_samples, bool)
        or not isinstance(bootstrap_samples, int)
        or bootstrap_samples <= 0
    ):
        raise ValueError("bootstrap_samples must be a positive integer")

    training_paths = validated_split_capture_paths(
        plan_path, "train", project_root=project_root
    )
    if split == "test":
        validated_split_capture_paths(
            plan_path, "validation", project_root=project_root
        )
    evaluation_paths = validated_split_capture_paths(
        plan_path, split, project_root=project_root
    )

    loaded = [
        load_ppo_artifact(
            path, plan_path=plan_path, training_paths=training_paths
        )
        for path in metadata_paths
    ]
    seeds = [artifact["seed"] for artifact, _ in loaded]
    if len(set(seeds)) != len(seeds):
        raise ValueError("PPO evaluation requires unique training seeds")
    configurations = [artifact["configuration"] for artifact, _ in loaded]
    if any(config != configurations[0] for config in configurations[1:]):
        raise ValueError("PPO artifacts do not share one frozen configuration")
    config = configurations[0]

    models: list[dict[str, Any]] = []
    for (artifact, model_path), seed in zip(loaded, seeds):
        predictor = predictor_loader(model_path)
        sessions = [
            _evaluate_capture(predictor, capture_path, config)
            for capture_path in evaluation_paths
        ]
        models.append(
            {
                "seed": seed,
                "model_file": model_path.name,
                "model_sha256": artifact["model_sha256"],
                "sessions": sessions,
                "mean_session_net_pnl": str(
                    _mean(
                        tuple(Decimal(item["net_pnl"]) for item in sessions)
                    )
                ),
            }
        )

    session_seed_means = []
    for index, capture_path in enumerate(evaluation_paths):
        values = tuple(
            Decimal(model["sessions"][index]["net_pnl"]) for model in models
        )
        session_seed_means.append(
            {
                "capture_file": capture_path.name,
                "capture_sha256": verify_capture(capture_path)["sha256"],
                "mean_net_pnl_across_seeds": str(_mean(values)),
                "minimum_net_pnl_across_seeds": str(min(values)),
                "maximum_net_pnl_across_seeds": str(max(values)),
            }
        )

    overall_values = tuple(
        Decimal(item["mean_net_pnl_across_seeds"])
        for item in session_seed_means
    )
    return {
        "ppo_evaluation_schema_version": PPO_EVALUATION_SCHEMA_VERSION,
        "study_plan_file": Path(plan_path).name,
        "study_plan_sha256": hashlib.sha256(Path(plan_path).read_bytes()).hexdigest(),
        "split": split,
        "test_confirmation_recorded": split == "test" and allow_test,
        "configuration": config,
        "model_count": len(models),
        "session_count": len(evaluation_paths),
        "models": models,
        "session_seed_means": session_seed_means,
        "bootstrap": {
            "seed": bootstrap_seed,
            "samples": bootstrap_samples,
            "unit": "capture_session_after_averaging_across_training_seeds",
        },
        "net_pnl_across_sessions": _distribution_summary(
            overall_values, bootstrap_seed, bootstrap_samples
        ),
        "claim_status": (
            "held-out test result; interpret against frozen baselines"
            if split == "test"
            else "validation result only; not a final performance claim"
        ),
    }


def _evaluate_capture(
    predictor: Predictor, capture_path: Path, config: dict[str, Any]
) -> dict[str, Any]:
    simulation = SimulationConfig(
        initial_cash=Decimal(config["initial_cash"]),
        maker_fee_rate=Decimal(config["maker_fee_rate"]),
        order_latency_ns=int(config["order_latency_ns"]),
        cancel_latency_ns=int(config["cancel_latency_ns"]),
        max_abs_inventory=Decimal(config["max_abs_inventory"]),
    )
    environment = QueueReplayEnv(
        (capture_path,),
        tick_size=Decimal(config["tick_size"]),
        quantity=Decimal(config["quantity"]),
        simulation_config=simulation,
        maximum_half_spread_ticks=int(config["maximum_half_spread_ticks"]),
        maximum_absolute_skew_ticks=int(config["maximum_absolute_skew_ticks"]),
        reward_scale=Decimal(config["reward_scale"]),
        inventory_penalty_per_second=Decimal(
            config["inventory_penalty_per_second"]
        ),
    )
    segments = []
    try:
        for segment_index in range(environment.capture_segment_counts[0]):
            observation, info = environment.reset(
                options={"capture_index": 0, "segment_index": segment_index}
            )
            maximum_inventory = abs(Decimal(info["inventory"]))
            while True:
                action, _ = predictor.predict(observation, deterministic=True)
                observation, _, terminated, truncated, info = environment.step(action)
                maximum_inventory = max(
                    maximum_inventory, abs(Decimal(info["inventory"]))
                )
                if terminated or truncated:
                    break
            segments.append(
                {
                    "segment_index": segment_index,
                    "decision_steps": info["episode_steps"],
                    "net_pnl": str(
                        Decimal(info["net_worth"]) - simulation.initial_cash
                    ),
                    "fills": info["total_fills"],
                    "turnover": info["turnover"],
                    "fees": info["fees"],
                    "final_inventory": info["inventory"],
                    "maximum_absolute_inventory": str(maximum_inventory),
                    "submitted_orders": info["submitted_orders"],
                    "rejected_orders": info["rejected_orders"],
                    "terminal_reason": info["reason"],
                }
            )
    finally:
        environment.close()
    return {
        "capture_file": capture_path.name,
        "capture_sha256": verify_capture(capture_path)["sha256"],
        "segment_count": len(segments),
        "net_pnl": str(
            sum((Decimal(item["net_pnl"]) for item in segments), Decimal("0"))
        ),
        "fills": sum(item["fills"] for item in segments),
        "turnover": str(
            sum((Decimal(item["turnover"]) for item in segments), Decimal("0"))
        ),
        "fees": str(
            sum((Decimal(item["fees"]) for item in segments), Decimal("0"))
        ),
        "segments": segments,
    }


def _distribution_summary(
    values: tuple[Decimal, ...], seed: int, samples: int
) -> dict[str, Any]:
    mean = _mean(values)
    if len(values) < 2:
        return {
            "sessions": len(values),
            "mean": str(mean),
            "sample_standard_deviation": None,
            "bootstrap_95_percent_lower": None,
            "bootstrap_95_percent_upper": None,
            "note": "at least two sessions are required for dispersion",
        }
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        variance = sum(
            ((value - mean) ** 2 for value in values), Decimal("0")
        ) / Decimal(len(values) - 1)
    random = _SplitMix64(seed)
    bootstrap_means = []
    for _ in range(samples):
        resample = tuple(values[random.next_u64() % len(values)] for _ in values)
        bootstrap_means.append(_mean(resample))
    bootstrap_means.sort()
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        last = Decimal(samples - 1)
        lower_index = int(
            (Decimal("0.025") * last).to_integral_value(rounding=ROUND_FLOOR)
        )
        upper_index = int(
            (Decimal("0.975") * last).to_integral_value(rounding=ROUND_CEILING)
        )
    return {
        "sessions": len(values),
        "mean": str(mean),
        "sample_standard_deviation": str(variance.sqrt()),
        "bootstrap_95_percent_lower": str(bootstrap_means[lower_index]),
        "bootstrap_95_percent_upper": str(bootstrap_means[upper_index]),
    }


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("cannot summarize an empty value sequence")
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        return sum(values, Decimal("0")) / Decimal(len(values))


class _SplitMix64:
    def __init__(self, seed: int) -> None:
        self.state = seed & ((1 << 64) - 1)

    def next_u64(self) -> int:
        mask = (1 << 64) - 1
        self.state = (self.state + 0x9E3779B97F4A7C15) & mask
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & mask
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & mask
        return (value ^ (value >> 31)) & mask
