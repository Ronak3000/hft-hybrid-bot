"""Train PPO only on a validated study-plan training split."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.market_data import verify_capture
from engine.research import load_study_plan, validated_split_capture_paths
from engine.simulation import SimulationConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--tick-size", type=Decimal, required=True)
    parser.add_argument("--quantity", type=Decimal, required=True)
    parser.add_argument("--initial-cash", type=Decimal, default=Decimal("1000000"))
    parser.add_argument("--maker-fee-rate", type=Decimal, default=Decimal("0"))
    parser.add_argument("--order-latency-ns", type=int, default=0)
    parser.add_argument("--cancel-latency-ns", type=int, default=0)
    parser.add_argument("--max-abs-inventory", type=Decimal, required=True)
    parser.add_argument("--max-half-spread-ticks", type=int, default=5)
    parser.add_argument("--max-absolute-skew-ticks", type=int, default=2)
    parser.add_argument("--reward-scale", type=Decimal, default=Decimal("1"))
    parser.add_argument(
        "--inventory-penalty-per-second", type=Decimal, default=Decimal("0")
    )
    parser.add_argument("--decision-interval-ns", type=int, default=0)
    parser.add_argument("--total-timesteps", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--learning-rate", type=float, default=0.0003)
    parser.add_argument("--entropy-coefficient", type=float, default=0.0)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--clip-range", type=float, default=0.2)
    parser.add_argument("--value-coefficient", type=float, default=0.5)
    parser.add_argument("--max-grad-norm", type=float, default=0.5)
    parser.add_argument("--n-epochs", type=int, default=10)
    parser.add_argument("--hidden-width", type=int, default=64)
    parser.add_argument("--hidden-layers", type=int, default=2)
    parser.add_argument("--torch-threads", type=int, default=1)
    parser.add_argument("--n-steps", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.suffix != ".zip":
        parser.error("--output must end in .zip")
    sidecar_path = args.output.with_suffix(".json")
    if args.output.exists() or sidecar_path.exists():
        parser.error("model or metadata output already exists")
    for field, value in (
        ("total_timesteps", args.total_timesteps),
        ("n_steps", args.n_steps),
        ("batch_size", args.batch_size),
    ):
        if isinstance(value, bool) or value <= 0:
            parser.error(f"--{field.replace('_', '-')} must be positive")
    if args.n_steps % args.batch_size:
        parser.error("--batch-size must divide --n-steps for one environment")
    if args.total_timesteps % args.n_steps:
        parser.error("--total-timesteps must be divisible by --n-steps")
    if args.seed < 0:
        parser.error("--seed must be non-negative")
    if args.decision_interval_ns < 0:
        parser.error("--decision-interval-ns must be non-negative")
    for field, value in (
        ("gamma", args.gamma),
        ("gae-lambda", args.gae_lambda),
    ):
        if not 0 < value <= 1:
            parser.error(f"--{field} must be in (0, 1]")
    for field, value in (
        ("clip-range", args.clip_range),
        ("value-coefficient", args.value_coefficient),
        ("max-grad-norm", args.max_grad_norm),
    ):
        if value <= 0:
            parser.error(f"--{field} must be positive")
    for field, value in (
        ("n-epochs", args.n_epochs),
        ("hidden-width", args.hidden_width),
        ("hidden-layers", args.hidden_layers),
        ("torch-threads", args.torch_threads),
    ):
        if isinstance(value, bool) or value <= 0:
            parser.error(f"--{field} must be positive")

    environment = None
    try:
        from stable_baselines3 import PPO
        import torch

        from engine.rl_trading.envs import QueueReplayEnv

        torch.set_num_threads(args.torch_threads)
        torch.use_deterministic_algorithms(True)

        training_paths = validated_split_capture_paths(
            args.plan, "train", project_root=PROJECT_ROOT
        )
        plan = load_study_plan(args.plan)
        config = SimulationConfig(
            initial_cash=args.initial_cash,
            maker_fee_rate=args.maker_fee_rate,
            order_latency_ns=args.order_latency_ns,
            cancel_latency_ns=args.cancel_latency_ns,
            max_abs_inventory=args.max_abs_inventory,
        )
        environment = QueueReplayEnv(
            training_paths,
            tick_size=args.tick_size,
            quantity=args.quantity,
            simulation_config=config,
            maximum_half_spread_ticks=args.max_half_spread_ticks,
            maximum_absolute_skew_ticks=args.max_absolute_skew_ticks,
            reward_scale=args.reward_scale,
            inventory_penalty_per_second=args.inventory_penalty_per_second,
            decision_interval_ns=args.decision_interval_ns,
        )
        model = PPO(
            "MlpPolicy",
            environment,
            learning_rate=args.learning_rate,
            ent_coef=args.entropy_coefficient,
            gamma=args.gamma,
            gae_lambda=args.gae_lambda,
            clip_range=args.clip_range,
            vf_coef=args.value_coefficient,
            max_grad_norm=args.max_grad_norm,
            n_epochs=args.n_epochs,
            n_steps=args.n_steps,
            batch_size=args.batch_size,
            policy_kwargs={
                "activation_fn": torch.nn.Tanh,
                "net_arch": [args.hidden_width] * args.hidden_layers,
            },
            seed=args.seed,
            device=args.device,
            verbose=1,
        )
        model.learn(total_timesteps=args.total_timesteps)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        model.save(str(args.output))
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    finally:
        if environment is not None:
            environment.close()

    if not args.output.is_file():
        parser.error("Stable-Baselines3 did not create the requested model")

    plan_bytes = args.plan.read_bytes()
    model_bytes = args.output.read_bytes()
    sidecar = {
        "ppo_artifact_schema_version": 1,
        "model_type": "Stable-Baselines3 PPO",
        "environment": "ApexHFTQueueReplay-v0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "model_byte_count": len(model_bytes),
        "study_plan_file": args.plan.name,
        "study_plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "training_captures": [
            {
                "capture_file": path.name,
                "sha256": verify_capture(path)["sha256"],
            }
            for path in training_paths
        ],
        "held_out_splits_used": [],
        "seed": args.seed,
        "total_timesteps": args.total_timesteps,
        "configuration": {
            "tick_size": str(args.tick_size),
            "quantity": str(args.quantity),
            "initial_cash": str(config.initial_cash),
            "maker_fee_rate": str(config.maker_fee_rate),
            "order_latency_ns": config.order_latency_ns,
            "cancel_latency_ns": config.cancel_latency_ns,
            "max_abs_inventory": str(config.max_abs_inventory),
            "maximum_half_spread_ticks": args.max_half_spread_ticks,
            "maximum_absolute_skew_ticks": args.max_absolute_skew_ticks,
            "reward_scale": str(args.reward_scale),
            "inventory_penalty_per_second": str(
                args.inventory_penalty_per_second
            ),
            "decision_interval_ns": args.decision_interval_ns,
            "learning_rate": args.learning_rate,
            "entropy_coefficient": args.entropy_coefficient,
            "gamma": args.gamma,
            "gae_lambda": args.gae_lambda,
            "clip_range": args.clip_range,
            "value_coefficient": args.value_coefficient,
            "max_grad_norm": args.max_grad_norm,
            "n_epochs": args.n_epochs,
            "hidden_width": args.hidden_width,
            "hidden_layers": args.hidden_layers,
            "torch_threads": args.torch_threads,
            "torch_deterministic_algorithms": True,
            "n_steps": args.n_steps,
            "batch_size": args.batch_size,
            "device": args.device,
        },
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("gymnasium", "numpy", "stable-baselines3", "torch")
        },
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "study_name": plan["study_name"],
        "claim_status": "training artifact only; no out-of-sample result",
    }
    with sidecar_path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
    print(f"Model: {args.output}")
    print(f"Metadata: {sidecar_path}")
    print("No validation or test captures were used by this training run.")


if __name__ == "__main__":
    main()
