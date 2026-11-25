"""Compare PPO, SAC, and Avellaneda–Stoikov on the same real L2 captures."""

from __future__ import annotations

import argparse
from bisect import bisect_left
from functools import lru_cache
import json
import sys
from dataclasses import asdict
from decimal import Decimal, localcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.research.trade_hawkes import load_arrivals
from engine.research.fill_probability import FrozenFillModel
from engine.research.l2_features import iter_l2_features
from engine.rl_trading.envs.arrival_quote_env import (
    OFFSET_TICKS, SIZE_FRACTIONS, ArrivalQuoteEnv, CausalTradeHistory,
)
from engine.rl_trading.envs.queue_replay_env import QueueReplayEnv
from engine.simulation import AvellanedaStoikovPolicy, InventorySkewPolicy, Side, SimulationConfig
from engine.simulation.queue_simulator import SIMULATION_DECIMAL_CONTEXT


def run(args):
    import stable_baselines3 as sb3
    import torch

    torch.set_num_threads(args.threads)
    splits = {name: [load_arrivals(path) for path in getattr(args, name)]
              for name in ("train", "validation", "test")}
    end, seen, markets = -1, set(), set()
    for sessions in splits.values():
        for session in sessions:
            first, last = session.bounds_ns
            if session.sha256 in seen or first <= end:
                raise ValueError("captures must be unique and strictly chronological")
            end = last
            seen.add(session.sha256)
            markets.add(session.market)
    if len(markets) != 1:
        raise ValueError("all replay sessions must use the same venue and symbol")
    hawkes = json.loads(args.hawkes_report.read_text(encoding="utf-8"))
    if (hawkes.get("event_clock") != "local_receive_ns"
            or hawkes.get("event_order") != ["aggressive_buy", "aggressive_sell"]
            or [item["sha256"] for item in hawkes["train"]] != [s.sha256 for s in splits["train"]]):
        raise ValueError("Hawkes fit must come from exactly these training captures in order")
    histories = {
        name: tuple(CausalTradeHistory(s, hawkes["decay_per_second"],
                                      hawkes["target_rows_baseline_then_source_amplitudes"])
                    for s in sessions)
        for name, sessions in splits.items()
    }
    fill_model = None
    fill_report_sha256 = None
    if args.fill_report is not None:
        from hashlib import sha256

        serialized = args.fill_report.read_bytes()
        fill_report = json.loads(serialized)
        for split in ("train", "validation"):
            if [s["sha256"] for s in fill_report["sessions"][split]] != [s.sha256 for s in splits[split]]:
                raise ValueError("fill probabilities must use exactly these training and validation captures")
        settings = fill_report["settings"]
        if (Decimal(settings["tick_size"]) != args.tick_size
                or settings["latency_ns"] != args.latency_ns
                or args.max_size not in {Decimal(value) for value in settings["sizes"]}):
            raise ValueError("fill forecast tick size, latency, and reference size must match replay")
        fill_model = FrozenFillModel(fill_report)
        fill_report_sha256 = sha256(serialized).hexdigest()
    config = SimulationConfig(
        maker_fee_rate=args.maker_fee_rate, order_latency_ns=args.latency_ns,
        cancel_latency_ns=args.latency_ns, max_abs_inventory=args.inventory_limit,
    )
    def make_env(split):
        base = QueueReplayEnv(
            tuple(s.path for s in splits[split]), tick_size=args.tick_size, quantity=args.max_size,
            simulation_config=config, observation_schema_version=2,
            inventory_penalty_per_second=args.inventory_penalty,
            record_fill_diagnostics=split != "train",
        )
        if any(count != 1 for count in base.capture_segment_counts):
            raise ValueError("the comparison requires one uninterrupted snapshot segment per capture")
        return ArrivalQuoteEnv(base, histories[split], fill_model, hide_fill_signal=args.fill_mode == "off")

    def evaluate(split, learned=None, baseline=None):
        env = make_env(split)
        rows = []
        try:
            for i in range(len(splits[split])):
                observation, _ = env.reset(options={"capture_index": i})
                policy = baseline() if baseline else None
                requested_qty = Decimal(0)
                requested_sides = 0
                decisions = 0
                done = False
                while not done:
                    if policy:
                        base = env.env
                        target = policy.quote(base.book, base.simulator.inventory,
                                              base.current_decision_time_ns)
                    else:
                        action, _ = learned.predict(observation, deterministic=True)
                        target = env.target(action)
                    sides = int(target.bid_price is not None) + int(target.ask_price is not None)
                    requested_sides += sides
                    requested_qty += target.quantity * sides
                    decisions += 1
                    observation, _, done, _, info = env.step_quote_target(target)
                if info["reason"] != "end_of_capture":
                    raise ValueError(f"{info['capture_file']}: incomplete replay ({info['reason']})")
                with localcontext(SIMULATION_DECIMAL_CONTEXT):
                    inventory = peak = Decimal(0)
                    simulator = env.env.simulator
                    for fill in simulator.fills:
                        inventory += fill.quantity if fill.side is Side.BUY else -fill.quantity
                        peak = max(peak, abs(inventory))
                    net = Decimal(info["net_worth"]) - config.initial_cash
                    submitted = sum((order.original_quantity for order in simulator.orders.values()), Decimal(0))
                    filled = sum((fill.quantity for fill in simulator.fills), Decimal(0))
                    markouts = post_fill_movement(splits[split][i].path, env.env.fill_diagnostics)
                rows.append({
                    "capture": info["capture_file"], "sha256": info["capture_sha256"],
                    "net_pnl": net, "fills": info["total_fills"], "submitted": info["submitted_orders"],
                    "fees": info["fees"], "turnover": info["turnover"], "peak_abs_inventory": peak,
                    "quantity_fill_rate": filled / submitted if submitted else None,
                    "requested_quote_quantity": requested_qty, "requested_sides": requested_sides,
                    "decisions": decisions,
                    "signed_post_fill_mid_move_pnl": markouts,
                })
        finally:
            env.close()
        return rows

    @lru_cache(maxsize=16)
    def post_fill_ticks(path):
        rows = list(iter_l2_features(path, levels=1))
        return [row.received_time_ns for row in rows], [row.mid_price for row in rows]

    def post_fill_movement(path, diagnostics):
        # Report-only: the policy never sees this table or these forward mids.
        times, mids = post_fill_ticks(path)
        result = {}
        for ms in (100, 1000):
            observed = 0
            total = Decimal(0)
            for fill in diagnostics:
                i = bisect_left(times, int(fill["received_time_ns"]) + ms * 1_000_000)
                if i == len(times):
                    continue
                sign = 1 if fill["side"] == Side.BUY.value else -1
                total += sign * (mids[i] - Decimal(fill["mid_at_fill"])) * Decimal(fill["quantity"])
                observed += 1
            result[str(ms)] = {"observed_fills": observed, "pnl": total if observed else None}
        return result

    def avellaneda():
        return AvellanedaStoikovPolicy(
            args.tick_size, args.max_size, Decimal("0.001"), Decimal("0.5"),
            Decimal(1), Decimal(60),
        )

    def skew(size=None):
        return InventorySkewPolicy(
            tick_size=args.tick_size, quantity=args.max_size if size is None else size,
            half_spread_ticks=256,
            max_abs_inventory=args.inventory_limit, max_skew_ticks=Decimal(128),
        )

    common = dict(seed=args.seed, verbose=0, device="cpu", batch_size=32,
                  policy_kwargs={"net_arch": [32, 32]})
    report = {
        "purpose": "single-seed development comparison",
        "sb3_version": sb3.__version__, "torch_version": torch.__version__, "seed": args.seed,
        "requested_steps": args.steps, "offset_ticks": OFFSET_TICKS,
        "size_fractions": SIZE_FRACTIONS, "max_quote_size": args.max_size,
        "tick_size": args.tick_size, "inventory_penalty_per_second": args.inventory_penalty,
        "simulation": asdict(config),
        "sessions": {name: [s.sha256 for s in sessions] for name, sessions in splits.items()},
        "hawkes": {"decay": hawkes["decay_per_second"],
                   "parameters": hawkes["target_rows_baseline_then_source_amplitudes"]},
        "fill_signal": {"mode": args.fill_mode, "report_sha256": fill_report_sha256,
                        "offsets": fill_model.offsets if fill_model else ()},
        "policies": {
            label: {split: evaluate(split, baseline=factory) for split in ("validation", "test")}
            for label, factory in (("avellaneda_stoikov", avellaneda), ("inventory_skew", skew))
        },
    }
    for name in args.algorithms:
        env = make_env("train")
        try:
            if name == "ppo":
                model = sb3.PPO("MlpPolicy", env, n_steps=128, n_epochs=3, **common)
            else:
                model = sb3.SAC("MlpPolicy", env, learning_starts=64,
                                buffer_size=max(1024, args.steps), train_freq=1, **common)
            model.learn(total_timesteps=args.steps)
            validation = evaluate("validation", learned=model)
            matched = validation_matched_size(validation, args.max_size)
            report["policies"][name] = {
                "trained_steps": model.num_timesteps,
                "validation": validation,
                "validation_matched_skew_size": matched,
                "test": evaluate("test", learned=model),
            }
            if matched is not None:
                report["policies"][f"inventory_skew_matched_to_{name}"] = {
                    "quote_size_frozen_from_validation": matched,
                    "test": evaluate("test", baseline=lambda: skew(matched)),
                }
            if args.weights_dir:
                args.weights_dir.mkdir(parents=True, exist_ok=True)
                with (args.weights_dir / f"{name}.zip").open("xb") as artifact:
                    model.save(artifact)
        finally:
            env.close()
    return report


def validation_matched_size(rows, maximum):
    """Round the validation-only mean active side size to the shared grid."""
    active = sum(row["requested_sides"] for row in rows)
    if not active:
        return None
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        mean = sum(row["requested_quote_quantity"] for row in rows) / active
        return min((maximum * fraction for fraction in SIZE_FRACTIONS if fraction),
                   key=lambda size: (abs(size - mean), size))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("train", "validation", "test"):
        parser.add_argument(f"--{name}", nargs="+", type=Path, required=True)
    parser.add_argument("--hawkes-report", required=True, type=Path)
    parser.add_argument("--fill-report", type=Path, help="run a matched off/on fill-feature ablation")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--weights-dir", type=Path)
    parser.add_argument("--steps", type=int, default=1024)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--seed", "--seeds", dest="seeds", nargs="+", type=int, default=[7])
    parser.add_argument("--algorithms", nargs="+", choices=("ppo", "sac"), default=("ppo", "sac"))
    parser.add_argument("--tick-size", type=Decimal, default=Decimal("0.01"))
    parser.add_argument("--max-size", type=Decimal, default=Decimal("0.001"))
    parser.add_argument("--maker-fee-rate", type=Decimal, default=Decimal("0.001"))
    parser.add_argument("--inventory-limit", type=Decimal, default=Decimal("0.01"))
    parser.add_argument("--inventory-penalty", type=Decimal, default=Decimal("0.1"))
    parser.add_argument("--latency-ns", type=int, default=1_000_000)
    args = parser.parse_args()
    if args.steps < 128 or args.steps % 128 or args.threads < 1 or min(args.seeds) < 0:
        parser.error("steps must be a positive multiple of 128, threads positive, and seed nonnegative")
    if (len(set(args.algorithms)) != len(args.algorithms) or len(set(args.seeds)) != len(args.seeds)
            or args.output.exists()):
        parser.error("use distinct algorithms and seeds and a previously unused output path")
    runs = []
    for seed in args.seeds:
        for mode in ("off", "on") if args.fill_report else ("absent",):
            options = argparse.Namespace(**vars(args), fill_mode=mode)
            options.seed = seed
            if options.weights_dir and (len(args.seeds) > 1 or args.fill_report):
                options.weights_dir = options.weights_dir / f"seed-{seed}-{mode}"
            if options.weights_dir and any((options.weights_dir / f"{a}.zip").exists() for a in args.algorithms):
                parser.error("use a weights directory without existing models for these algorithms")
            runs.append(options)
    try:
        reports = [run(options) for options in runs]
        report = reports[0] if len(reports) == 1 else {
            "purpose": "development comparison on shared test sessions",
            "seeds": args.seeds, "fill_signal_ablation": bool(args.fill_report),
            ("runs" if args.fill_report else "per_seed"): reports,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as destination:
            json.dump(report, destination, indent=2, default=str, allow_nan=False)
            destination.write("\n")
    except (OSError, ValueError, ArithmeticError) as exc:
        parser.error(str(exc))
    print(f"Arrival-aware queue policy report: {args.output}")


if __name__ == "__main__":
    main()
