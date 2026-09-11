"""Paired PPO and baseline evaluation on identical queue-replay episodes."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from engine.market_data import L2Book, verify_capture
from engine.rl_trading.envs import QueueReplayEnv
from engine.simulation import (
    AvellanedaStoikovPolicy,
    FixedSpreadPolicy,
    InventorySkewPolicy,
    QuotePolicy,
    SeededRandomPolicy,
    SimulationConfig,
)

from .as_calibration import load_calibration
from .ppo_evaluation import (
    PredictorLoader,
    _distribution_summary,
    _mean,
    evaluate_ppo_artifacts,
)
from .study_plan import validated_split_capture_paths


PAIRED_EVALUATION_SCHEMA_VERSION = 1
PolicyFactory = Callable[[int], QuotePolicy]


def evaluate_paired_queue_policies(
    plan_path: str | Path,
    split: str,
    metadata_paths: tuple[str | Path, ...],
    calibration_path: str | Path,
    *,
    project_root: str | Path,
    predictor_loader: PredictorLoader,
    allow_test: bool = False,
    fixed_half_spread_ticks: int = 1,
    inventory_max_skew_ticks: Decimal = Decimal("2"),
    random_seed: int = 101,
    as_risk_aversion: Decimal = Decimal("0.001"),
    as_session_horizon_seconds: Decimal = Decimal("1000"),
    bootstrap_seed: int = 17,
    bootstrap_samples: int = 2000,
) -> dict[str, Any]:
    """Compare seed-averaged PPO with four baselines by capture session."""
    ppo = evaluate_ppo_artifacts(
        plan_path,
        split,
        metadata_paths,
        project_root=project_root,
        predictor_loader=predictor_loader,
        allow_test=allow_test,
        bootstrap_seed=bootstrap_seed,
        bootstrap_samples=bootstrap_samples,
    )
    training_paths = validated_split_capture_paths(
        plan_path, "train", project_root=project_root
    )
    evaluation_paths = validated_split_capture_paths(
        plan_path, split, project_root=project_root
    )
    calibration = load_calibration(calibration_path)
    expected_sources = [
        {"capture_file": path.name, "sha256": verify_capture(path)["sha256"]}
        for path in training_paths
    ]
    actual_sources = [
        {
            "capture_file": item.get("capture_file"),
            "sha256": item.get("sha256"),
        }
        for item in calibration["source_captures"]
    ]
    if actual_sources != expected_sources:
        raise ValueError("baseline calibration does not match the training split")

    config = ppo["configuration"]
    tick_size = Decimal(config["tick_size"])
    quantity = Decimal(config["quantity"])
    max_inventory = Decimal(config["max_abs_inventory"])
    policy_factories: dict[str, PolicyFactory] = {
        "fixed_spread": lambda _: FixedSpreadPolicy(
            tick_size, quantity, fixed_half_spread_ticks
        ),
        "inventory_skew": lambda _: InventorySkewPolicy(
            tick_size,
            quantity,
            fixed_half_spread_ticks,
            max_inventory,
            inventory_max_skew_ticks,
        ),
        "seeded_random": lambda segment: SeededRandomPolicy(
            tick_size=tick_size,
            quantity=quantity,
            seed=random_seed + segment,
            minimum_half_spread_ticks=1,
            maximum_half_spread_ticks=int(config["maximum_half_spread_ticks"]),
            maximum_absolute_skew_ticks=int(
                config["maximum_absolute_skew_ticks"]
            ),
        ),
        "avellaneda_stoikov": lambda _: AvellanedaStoikovPolicy(
            tick_size=tick_size,
            quantity=quantity,
            risk_aversion=as_risk_aversion,
            volatility=Decimal(calibration["volatility_per_sqrt_second"]),
            intensity_decay=Decimal(calibration["intensity_decay"]),
            session_horizon_seconds=as_session_horizon_seconds,
        ),
    }

    baselines: dict[str, Any] = {}
    paired: dict[str, Any] = {}
    ppo_values = tuple(
        Decimal(item["mean_net_pnl_across_seeds"])
        for item in ppo["session_seed_means"]
    )
    for policy_index, (name, factory) in enumerate(policy_factories.items()):
        sessions = [
            _evaluate_policy_capture(path, config, factory)
            for path in evaluation_paths
        ]
        baseline_values = tuple(Decimal(item["net_pnl"]) for item in sessions)
        baselines[name] = {
            "sessions": sessions,
            "net_pnl_across_sessions": _distribution_summary(
                baseline_values,
                bootstrap_seed + 10 + policy_index,
                bootstrap_samples,
            ),
        }
        differences = tuple(
            ppo_value - baseline_value
            for ppo_value, baseline_value in zip(ppo_values, baseline_values)
        )
        paired[f"ppo_seed_mean_minus_{name}"] = _distribution_summary(
            differences,
            bootstrap_seed + 100 + policy_index,
            bootstrap_samples,
        )

    calibration_file = Path(calibration_path)
    return {
        "paired_evaluation_schema_version": PAIRED_EVALUATION_SCHEMA_VERSION,
        "split": split,
        "comparison_unit": "capture_session_with_snapshot_segment_resets",
        "ppo": ppo,
        "calibration_file": calibration_file.name,
        "calibration_sha256": hashlib.sha256(
            calibration_file.read_bytes()
        ).hexdigest(),
        "baseline_configuration": {
            "fixed_half_spread_ticks": fixed_half_spread_ticks,
            "inventory_max_skew_ticks": str(inventory_max_skew_ticks),
            "random_seed": random_seed,
            "random_seed_rule": "base seed plus zero-based segment index",
            "as_risk_aversion": str(as_risk_aversion),
            "as_session_horizon_seconds": str(as_session_horizon_seconds),
        },
        "baselines": baselines,
        "paired_net_pnl_differences": paired,
        "claim_status": (
            "final pilot comparison; only session-level uncertainty is supported"
            if split == "test"
            else "validation comparison only; final test remains sealed"
        ),
    }


def _evaluate_policy_capture(
    capture_path: Path,
    config: dict[str, Any],
    policy_factory: PolicyFactory,
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
            policy = policy_factory(segment_index)
            _, info = environment.reset(
                options={"capture_index": 0, "segment_index": segment_index}
            )
            maximum_inventory = Decimal("0")
            while True:
                book = environment.book
                if not isinstance(book, L2Book):
                    raise RuntimeError("queue environment has no active L2 book")
                target = policy.quote(
                    book,
                    environment.simulator.inventory,
                    environment.current_decision_time_ns,
                )
                _, _, terminated, truncated, info = environment.step_quote_target(
                    target
                )
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
        "mean_segment_net_pnl": str(
            _mean(tuple(Decimal(item["net_pnl"]) for item in segments))
        ),
        "segments": segments,
    }
