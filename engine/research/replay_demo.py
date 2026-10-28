"""Produce sampled browser playback from the real queue-replay execution path."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from heapq import nlargest, nsmallest
from pathlib import Path
from typing import Any

from engine.market_data import verify_capture
from engine.rl_trading.envs import QueueReplayEnv
from engine.simulation import FixedSpreadPolicy, InventorySkewPolicy, NoQuotePolicy, Side, SimulationConfig
from engine.simulation.queue_simulator import SIMULATION_DECIMAL_CONTEXT

from .study_plan import load_study_plan, validated_split_capture_paths
from .ppo_evaluation import Predictor, PredictorLoader, load_ppo_artifact


DEMO_SCHEMA_VERSION = 1
GENERATOR = "ApexHFT training replay demo v1"
POLICY_LABELS = {
    "inventory_skew": "Inventory skew",
    "fixed_spread": "Fixed spread",
    "no_quote": "No quote",
}
EXTRA_POLICY_LABELS = {"widest_fixed": "Fixed · widest grid", "ppo": "PPO v2"}


def build_replay_segment(
    capture_path: Path,
    policy_name: str,
    segment_index: int,
    *,
    tick_size: Decimal,
    quantity: Decimal,
    config: SimulationConfig,
    half_spread_ticks: int = 5,
    max_skew_ticks: Decimal = Decimal("2"),
    decision_interval_ns: int = 250_000_000,
    sample_interval_ns: int = 1_000_000_000,
    predictor: Predictor | None = None,
    model_configuration: dict[str, Any] | None = None,
    model_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if policy_name not in {**POLICY_LABELS, **EXTRA_POLICY_LABELS}:
        raise ValueError("unsupported demo policy")
    if policy_name == "ppo" and (predictor is None or model_configuration is None or model_provenance is None):
        raise ValueError("PPO replay requires a predictor, frozen configuration, and model provenance")
    if isinstance(sample_interval_ns, bool) or not isinstance(sample_interval_ns, int) or sample_interval_ns <= 0:
        raise ValueError("sample_interval_ns must be a positive integer")
    frozen = model_configuration or {}
    if policy_name == "widest_fixed":
        half_spread_ticks = max(frozen.get("half_spread_tick_choices") or [frozen.get("maximum_half_spread_ticks", 5)])
    policies = {
        "fixed_spread": lambda: FixedSpreadPolicy(tick_size, quantity, half_spread_ticks),
        "inventory_skew": lambda: InventorySkewPolicy(tick_size, quantity, half_spread_ticks, config.max_abs_inventory, max_skew_ticks),
        "no_quote": lambda: NoQuotePolicy(quantity),
        "widest_fixed": lambda: FixedSpreadPolicy(tick_size, quantity, half_spread_ticks),
    }
    policy = None if policy_name == "ppo" else policies[policy_name]()
    env = QueueReplayEnv(
        (capture_path,), tick_size=tick_size, quantity=quantity,
        simulation_config=config, decision_interval_ns=decision_interval_ns,
        maximum_half_spread_ticks=int(frozen.get("maximum_half_spread_ticks", 5)),
        maximum_absolute_skew_ticks=int(frozen.get("maximum_absolute_skew_ticks", 2)),
        half_spread_tick_choices=frozen.get("half_spread_tick_choices"),
        action_schema_version=int(frozen.get("action_schema_version", 1)),
        observation_schema_version=int(frozen.get("observation_schema_version", 1)),
        entry_fee_buffer_bps=frozen.get("entry_fee_buffer_bps"),
        reward_scale=Decimal(frozen.get("reward_scale", "1")),
        inventory_penalty_per_second=Decimal(frozen.get("inventory_penalty_per_second", "0")),
    )
    frames: list[dict[str, Any]] = []
    try:
        observation, info = env.reset(options={"capture_index": 0, "segment_index": segment_index})
        start_ns = info["decision_time_ns"]
        last_decision = None

        def frame() -> dict[str, Any]:
            assert env.book is not None
            book = env.book
            with localcontext(SIMULATION_DECIMAL_CONTEXT):
                mid = (book.best_bid + book.best_ask) / Decimal("2")
                pnl = Decimal(info["net_worth"]) - config.initial_cash
            quotes = {}
            for side in Side:
                order = env.simulator.open_order(side)
                quotes[side.value] = None if order is None else {
                    "price": str(order.price), "quantity": str(order.remaining_quantity),
                    "queue_ahead": str(order.queue_ahead), "status": order.status.value,
                    "cancel_pending": order.cancel_effective_time_ns is not None,
                }
            return {
                "elapsed_ms": (info["decision_time_ns"] - start_ns) / 1_000_000,
                "time_ms": info["decision_time_ns"] // 1_000_000,
                "received_time_ns": str(info["decision_time_ns"]),
                "mid": str(mid), "pnl": str(pnl), "cash": info["cash"],
                "inventory": info["inventory"], "fees": info["fees"],
                "turnover": info["turnover"], "fill_count": info["total_fills"],
                "bids": [[str(p), str(book.bids[p])] for p in nlargest(5, book.bids)],
                "asks": [[str(p), str(book.asks[p])] for p in nsmallest(5, book.asks)],
                "quotes": quotes,
                "decision": last_decision,
            }

        frames.append(frame())
        while True:
            assert env.book is not None
            if predictor is not None and policy_name == "ppo":
                action, _ = predictor.predict(observation, deterministic=True)
                last_decision = env.action_parameters(action)
                observation, _, terminated, truncated, info = env.step(action)
            else:
                assert policy is not None
                target = policy.quote(env.book, env.simulator.inventory, env.current_decision_time_ns)
                observation, _, terminated, truncated, info = env.step_quote_target(target)
            done = terminated or truncated
            if done or info["decision_time_ns"] - int(frames[-1]["received_time_ns"]) >= sample_interval_ns:
                current = frame()
                if current["received_time_ns"] == frames[-1]["received_time_ns"]:
                    frames[-1] = current
                else:
                    frames.append(current)
            if done:
                break
        fills = [{
            "order_id": str(fill.order_id), "trade_id": str(fill.trade_id),
            "time_ms": fill.received_time_ns // 1_000_000,
            "elapsed_ms": (fill.received_time_ns - start_ns) / 1_000_000,
            "side": fill.side.value, "price": str(fill.price),
            "quantity": str(fill.quantity), "fee": str(fill.fee),
        } for fill in env.simulator.fills]
        return {
            "schema_version": DEMO_SCHEMA_VERSION,
            "generator": GENERATOR,
            "scope": "Training-capture illustration; not held-out evaluation or live execution.",
            "source": {
                "capture_file": capture_path.name,
                "capture_sha256": env.capture_hashes[0],
                "segment_index": segment_index,
                "segment_count": env.capture_segment_counts[0],
            },
            "policy": {
                "id": policy_name,
                "label": f"PPO{' + fee guard' if frozen.get('entry_fee_buffer_bps') is not None else ' v2'} · seed {model_provenance['seed']}" if policy_name == "ppo" else {**POLICY_LABELS, **EXTRA_POLICY_LABELS}[policy_name],
                "kind": "Trained PPO" if policy_name == "ppo" else "Rule-based baseline",
            },
            "model": model_provenance if policy_name == "ppo" else None,
            "configuration": {
                "tick_size": str(tick_size), "quantity": str(quantity),
                "initial_cash": str(config.initial_cash), "maker_fee_rate": str(config.maker_fee_rate),
                "order_latency_ns": config.order_latency_ns, "cancel_latency_ns": config.cancel_latency_ns,
                "max_abs_inventory": str(config.max_abs_inventory),
                "half_spread_ticks": None if policy_name == "ppo" else half_spread_ticks,
                "max_skew_ticks": str(max_skew_ticks),
                "decision_interval_ns": decision_interval_ns, "sample_interval_ns": sample_interval_ns,
                "entry_fee_buffer_bps": frozen.get("entry_fee_buffer_bps"),
            },
            "summary": {**{key: frames[-1][key] for key in ("pnl", "cash", "inventory", "fees", "turnover", "fill_count")},
                        "duration_ms": frames[-1]["elapsed_ms"], "decision_steps": info["episode_steps"],
                        "terminal_reason": info["reason"]},
            "frames": frames, "fills": fills,
        }
    finally:
        env.close()


def export_training_demo(
    plan_path: Path, project_root: Path, output: Path, *,
    ppo_metadata: Path | None = None, predictor_loader: PredictorLoader | None = None,
    entry_fee_buffer_bps: Decimal | None = None,
) -> dict[str, Any]:
    training = validated_split_capture_paths(plan_path, "train", project_root=project_root)
    plan = load_study_plan(plan_path)
    selected = tuple(dict.fromkeys((training[0], training[-1])))
    output.mkdir(parents=True, exist_ok=True)
    catalog_path = output / "catalog.json"
    if catalog_path.exists() and json.loads(catalog_path.read_text()).get("generator") != GENERATOR:
        raise FileExistsError("refusing to replace a catalog from another producer")
    config = SimulationConfig(
        initial_cash=Decimal("1000000"), maker_fee_rate=Decimal("0.001"),
        order_latency_ns=1_000_000, cancel_latency_ns=1_000_000,
        max_abs_inventory=Decimal("0.01"),
    )
    predictor = None
    frozen: dict[str, Any] = {}
    provenance = None
    policies = list(POLICY_LABELS)
    if entry_fee_buffer_bps is not None and ppo_metadata is None:
        raise ValueError("an explicit PPO checkpoint is required for an entry-guard overlay")
    if ppo_metadata is not None:
        artifact, model_path = load_ppo_artifact(
            ppo_metadata, plan_path=plan_path, training_paths=training
        )
        frozen = dict(artifact["configuration"])
        if entry_fee_buffer_bps is not None:
            if frozen.get("entry_fee_buffer_bps") is not None:
                raise ValueError("an external overlay requires an unguarded source checkpoint")
            if not entry_fee_buffer_bps.is_finite() or entry_fee_buffer_bps < 0:
                raise ValueError("entry fee buffer must be non-negative and finite")
            frozen["entry_fee_buffer_bps"] = str(entry_fee_buffer_bps)
        config = SimulationConfig(
            initial_cash=Decimal(frozen["initial_cash"]),
            maker_fee_rate=Decimal(frozen["maker_fee_rate"]),
            order_latency_ns=int(frozen["order_latency_ns"]),
            cancel_latency_ns=int(frozen["cancel_latency_ns"]),
            max_abs_inventory=Decimal(frozen["max_abs_inventory"]),
        )
        if predictor_loader is None:
            import torch
            from stable_baselines3 import PPO
            torch.set_num_threads(1)
            predictor = PPO.load(model_path, device="cpu")
        else:
            predictor = predictor_loader(model_path)
        if hasattr(predictor, "num_timesteps") and predictor.num_timesteps != artifact["total_timesteps"]:
            raise ValueError("model training budget does not match its sidecar")
        provenance = {
            "model_file": model_path.name, "model_sha256": artifact["model_sha256"],
            "metadata_file": ppo_metadata.name,
            "metadata_sha256": hashlib.sha256(ppo_metadata.read_bytes()).hexdigest(),
            "seed": artifact["seed"], "total_timesteps": artifact["total_timesteps"],
            "training_capture_count": len(training),
            "action_schema_version": int(frozen.get("action_schema_version", 1)),
            "observation_schema_version": int(frozen.get("observation_schema_version", 1)),
            "half_spread_tick_choices": frozen.get("half_spread_tick_choices"),
            "claim_status": "Single-seed training illustration; not held-out evaluation.",
            "policy_overlay": None if entry_fee_buffer_bps is None else {
                "entry_fee_buffer_bps": str(entry_fee_buffer_bps),
                "trained_with_overlay": False,
                "scope": "External rule applied to this frozen checkpoint and all displayed controls",
            },
        }
        policies = ["ppo", *policies, "widest_fixed"]
    sessions = []
    for path in selected:
        source = verify_capture(path)
        session_id = next(s["session_id"] for s in plan["sessions"] if s["capture_file"] == path.name)
        probe = QueueReplayEnv((path,), tick_size="0.01", quantity="0.001")
        segment_count = probe.capture_segment_counts[0]
        probe.close()
        for segment in range(segment_count):
            session = {
                "id": f"{session_id}-s{segment}",
                "label": session_id + (f" · segment {segment + 1}" if segment_count > 1 else ""),
                "split": "train", "captured_at_utc": source["metadata"]["captured_at_utc"],
                "capture_sha256": source["sha256"], "runs": [],
            }
            for policy_name in policies:
                print(f"Exporting {session_id}, segment {segment}, {policy_name}...", flush=True)
                run = build_replay_segment(
                    path, policy_name, segment,
                    tick_size=Decimal(frozen.get("tick_size", "0.01")),
                    quantity=Decimal(frozen.get("quantity", "0.001")), config=config,
                    decision_interval_ns=int(frozen.get("decision_interval_ns", 250_000_000)),
                    model_configuration=frozen, predictor=predictor,
                    model_provenance=provenance,
                )
                raw = (json.dumps(run, sort_keys=True, separators=(",", ":")) + "\n").encode()
                digest = hashlib.sha256(raw).hexdigest()
                filename = f"{session_id}-s{segment}-{policy_name}-{digest[:16]}.json"
                destination = output / filename
                if destination.exists():
                    if destination.read_bytes() != raw:
                        raise FileExistsError(f"content-addressed replay changed: {filename}")
                else:
                    with destination.open("xb") as stream:
                        stream.write(raw)
                session["runs"].append({
                    "policy": policy_name, "label": run["policy"]["label"],
                    "file": filename, "sha256": digest, "byte_count": len(raw),
                    "frames": len(run["frames"]), "summary": run["summary"],
                })
            sessions.append(session)
    catalog = {
        "schema_version": DEMO_SCHEMA_VERSION, "generator": GENERATOR,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "study_name": plan["study_name"],
        "study_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "training_sessions_validated": len(training),
        "selection_rule": "first and last training capture by planned ordinal, including every snapshot segment",
        "held_out_splits_used": [], "sessions": sessions,
        "model": provenance,
    }
    temporary = output / f".catalog-{os.getpid()}.tmp"
    created_temporary = False
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            created_temporary = True
            stream.write(json.dumps(catalog, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, catalog_path)
    finally:
        if created_temporary:
            temporary.unlink(missing_ok=True)
    return catalog
