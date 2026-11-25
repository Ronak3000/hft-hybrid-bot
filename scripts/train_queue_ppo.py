"""Train PPO only on a validated study-plan training split."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.market_data import verify_capture
from engine.research import load_study_plan, validated_split_capture_paths
from engine.research.l2_features import iter_l2_features
from engine.simulation import SimulationConfig
from engine.simulation.quote_grid import quote_grid_economics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--plan", type=Path)
    source.add_argument("--archive-window", type=Path, help="Verified dated Binance archive capture from the workbench")
    source.add_argument("--archive-dataset", type=Path, help="Complete, hash-sealed multi-window archive manifest")
    source.add_argument("--recorded-window", type=Path, help="Previously recorded Binance depth/trade session")
    parser.add_argument("--tick-size", type=Decimal, required=True)
    parser.add_argument("--quantity", type=Decimal, required=True)
    parser.add_argument("--initial-cash", type=Decimal, default=Decimal("1000000"))
    parser.add_argument("--maker-fee-rate", type=Decimal, default=Decimal("0"))
    parser.add_argument("--order-latency-ns", type=int, default=0)
    parser.add_argument("--cancel-latency-ns", type=int, default=0)
    parser.add_argument("--max-abs-inventory", type=Decimal, required=True)
    parser.add_argument("--max-half-spread-ticks", type=int, default=5)
    parser.add_argument("--half-spread-tick-choices", type=int, nargs="+")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--require-fee-coverage", action="store_true")
    parser.add_argument("--max-absolute-skew-ticks", type=int, default=2)
    parser.add_argument("--reward-scale", type=Decimal, default=Decimal("1"))
    parser.add_argument(
        "--inventory-penalty-per-second", type=Decimal, default=Decimal("0")
    )
    parser.add_argument("--decision-interval-ns", type=int, default=0)
    parser.add_argument(
        "--action-schema-version", type=int, choices=(1, 2, 3), default=1
    )
    parser.add_argument("--observation-schema-version", type=int, choices=(1, 2), default=1)
    parser.add_argument("--entry-fee-buffer-bps", type=Decimal)
    parser.add_argument("--total-timesteps", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--learning-rate", type=float, default=0.0003)
    parser.add_argument("--entropy-coefficient", type=float, default=0.0)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--clip-range", type=float, default=0.2)
    parser.add_argument("--clip-range-vf", type=float)
    parser.add_argument("--target-kl", type=float)
    parser.add_argument("--normalize-advantage", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--orthogonal-init", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--activation", choices=("tanh", "relu"), default="tanh")
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

        if args.plan:
            training_paths = validated_split_capture_paths(args.plan, "train", project_root=PROJECT_ROOT)
            plan = load_study_plan(args.plan)
        elif args.recorded_window:
            from engine.market_data.history import validate
            from datetime import timedelta
            path = args.recorded_window
            meta = verify_capture(path)["metadata"]
            if meta.get("venue") != "binance_spot" or meta.get("source") != "Binance Spot REST snapshot + combined diff-depth/trade WebSocket":
                raise ValueError("Expected a directly recorded Binance depth/trade session.")
            validate(path)
            with path.open(encoding="utf-8") as source:
                times = (r["received_time_ns"] for r in map(json.loads, source) if r["kind"] != "metadata")
                first = last = next(times)
                for ns in times:
                    first, last = min(first, ns), max(last, ns)
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            window_meta = {**meta, "start": (epoch + timedelta(microseconds=first//1000)).isoformat(),
                           "end": (epoch + timedelta(microseconds=last//1000+1)).isoformat()}
            training_paths = (path,)
        elif args.archive_dataset:
            from engine.market_data.history import load_dataset
            window_meta, training_paths = load_dataset(args.archive_dataset)
            from math import ceil
            duration = (datetime.fromisoformat(window_meta["end"]) - datetime.fromisoformat(window_meta["start"])).total_seconds()
            minimum_steps = ceil(duration / (args.decision_interval_ns / 1e9)) if args.decision_interval_ns else 0
            if args.total_timesteps < minimum_steps:
                raise ValueError(f"At least {minimum_steps} steps (rounded up to a rollout multiple) are required to cover this dataset once.")
        else:
            from engine.market_data.history import validate
            validate(args.archive_window)
            training_paths = (args.archive_window,)
            window_meta = verify_capture(args.archive_window)["metadata"]
            if window_meta["source"] != "Tardis raw Binance Spot depthSnapshot/depth/trade":
                raise ValueError("Expected a dated Binance Spot archive.")
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
            action_schema_version=args.action_schema_version,
            half_spread_tick_choices=args.half_spread_tick_choices,
            observation_schema_version=args.observation_schema_version,
            entry_fee_buffer_bps=args.entry_fee_buffer_bps,
        )
        # Read only a training reference, without advancing the environment's
        # episode counter or changing the order of training captures.
        with closing(iter_l2_features(training_paths[0], levels=1)) as features:
            try:
                reference = next(features)
            except StopIteration as exc:
                raise ValueError("training capture has no usable L2 reference") from exc
        preflight = quote_grid_economics(
            reference.mid_price, args.tick_size, config.maker_fee_rate,
            environment.half_spread_tick_choices,
        )
        preflight["reference_capture"] = training_paths[0].name
        preflight["reference_capture_sha256"] = environment.capture_hashes[0]
        preflight["reference_received_time_ns"] = reference.received_time_ns
        preflight["held_out_splits_used"] = []
        if args.preflight_only:
            print(json.dumps(preflight, indent=2, sort_keys=True))
            if args.require_fee_coverage and not preflight["has_fee_covering_valid_width"]:
                raise ValueError("no valid quote width covers fees at the training reference")
            return
        if not preflight["has_fee_covering_valid_width"]:
            if args.require_fee_coverage:
                raise ValueError("no valid quote width covers fees at the training reference")
            print("WARNING: no quote width covers fees at the training reference; see metadata preflight.")
        model = PPO(
            "MlpPolicy",
            environment,
            learning_rate=args.learning_rate,
            ent_coef=args.entropy_coefficient,
            gamma=args.gamma,
            gae_lambda=args.gae_lambda,
            clip_range=args.clip_range,
            clip_range_vf=args.clip_range_vf,
            target_kl=args.target_kl,
            normalize_advantage=args.normalize_advantage,
            vf_coef=args.value_coefficient,
            max_grad_norm=args.max_grad_norm,
            n_epochs=args.n_epochs,
            n_steps=args.n_steps,
            batch_size=args.batch_size,
            policy_kwargs={
                "activation_fn": torch.nn.Tanh if args.activation == "tanh" else torch.nn.ReLU,
                "ortho_init": args.orthogonal_init,
                "net_arch": [args.hidden_width] * args.hidden_layers,
            },
            seed=args.seed,
            device=args.device,
            verbose=1,
        )
        model.learn(total_timesteps=args.total_timesteps)
        if (args.archive_dataset or args.recorded_window) and environment.completed_capture_indices != set(range(len(training_paths))):
            raise ValueError("Training budget did not complete every selected capture; increase total timesteps.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        model.save(str(args.output))
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    finally:
        if environment is not None:
            environment.close()

    if not args.output.is_file():
        parser.error("Stable-Baselines3 did not create the requested model")

    model_bytes = args.output.read_bytes()
    sidecar = {
        "ppo_artifact_schema_version": 1,
        "model_type": "Stable-Baselines3 PPO",
        "environment": "ApexHFTQueueReplay-v0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "model_byte_count": len(model_bytes),
        **({"study_plan_file": args.plan.name,
            "study_plan_sha256": hashlib.sha256(args.plan.read_bytes()).hexdigest(),
            "study_name": plan["study_name"]} if args.plan else
           {"archive_window": {key: window_meta[key] for key in ("symbol", "start", "end", "source")}}),
        **({"archive_dataset_file": args.archive_dataset.name,
            "archive_dataset_sha256": hashlib.sha256(args.archive_dataset.read_bytes()).hexdigest(),
            "episode_reset_minutes": window_meta["episode_reset_minutes"]} if args.archive_dataset else {}),
        "training_captures": [
            {
                "capture_file": path.name,
                "sha256": verify_capture(path)["sha256"],
            }
            for path in training_paths
        ],
        "held_out_splits_used": [],
        "quote_economics_preflight": preflight,
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
            "half_spread_tick_choices": args.half_spread_tick_choices,
            "maximum_absolute_skew_ticks": args.max_absolute_skew_ticks,
            "reward_scale": str(args.reward_scale),
            "inventory_penalty_per_second": str(
                args.inventory_penalty_per_second
            ),
            "decision_interval_ns": args.decision_interval_ns,
            "action_schema_version": args.action_schema_version,
            "observation_schema_version": args.observation_schema_version,
            "entry_fee_buffer_bps": None if args.entry_fee_buffer_bps is None else str(args.entry_fee_buffer_bps),
            "learning_rate": args.learning_rate,
            "entropy_coefficient": args.entropy_coefficient,
            "gamma": args.gamma,
            "gae_lambda": args.gae_lambda,
            "clip_range": args.clip_range,
            "clip_range_vf": args.clip_range_vf,
            "target_kl": args.target_kl,
            "normalize_advantage": args.normalize_advantage,
            "activation": args.activation,
            "orthogonal_init": args.orthogonal_init,
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
        "claim_status": "training artifact only; no out-of-sample result",
    }
    with sidecar_path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
    print(f"Model: {args.output}")
    print(f"Metadata: {sidecar_path}")
    print("No validation or test captures were used by this training run.")


if __name__ == "__main__":
    main()
