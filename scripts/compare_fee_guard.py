"""Training-only, same-checkpoint comparison of an explicit entry-cost overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal, localcontext
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.research.study_plan import validated_split_capture_paths
from engine.research.ppo_evaluation import load_ppo_artifact, _evaluate_capture
from engine.simulation.queue_simulator import SIMULATION_DECIMAL_CONTEXT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--buffer-bps", type=Decimal, default=Decimal("0"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError("report already exists")
        if not args.buffer_bps.is_finite() or args.buffer_bps < 0:
            raise ValueError("buffer must be non-negative and finite")
        paths = validated_split_capture_paths(args.plan, "train", project_root=PROJECT_ROOT)
        artifact, model_path = load_ppo_artifact(args.model, plan_path=args.plan, training_paths=paths)
        if artifact["configuration"].get("entry_fee_buffer_bps") is not None:
            raise ValueError("this comparison requires an unguarded source checkpoint")
        import torch
        from stable_baselines3 import PPO
        torch.set_num_threads(1)
        predictor = PPO.load(model_path, device="cpu")
        if predictor.num_timesteps != artifact["total_timesteps"]:
            raise ValueError("model budget does not match sidecar")
        variants = []
        for label, buffer in (("unguarded", None), ("entry_cost_guard", str(args.buffer_bps))):
            configuration = {**artifact["configuration"], "entry_fee_buffer_bps": buffer}
            sessions = []
            for capture in paths:
                print(f"{label}: {capture.stem}", flush=True)
                sessions.append(_evaluate_capture(predictor, capture, configuration, fill_diagnostics=True))
            with localcontext(SIMULATION_DECIMAL_CONTEXT):
                total = lambda key: sum((Decimal(session[key]) for session in sessions), Decimal("0"))
                spread = sum((Decimal(segment["fill_diagnostics"]["spread_capture"]) for session in sessions for segment in session["segments"]), Decimal("0"))
                below = sum(segment["fill_diagnostics"]["instant_edge_below_fee_fills"] for session in sessions for segment in session["segments"])
                aggregate = {"net_pnl": str(total("net_pnl")), "gross_pnl": str(total("net_pnl") + total("fees")),
                             "fees": str(total("fees")), "fills": int(total("fills")), "turnover": str(total("turnover")),
                             "spread_capture": str(spread), "inventory_revaluation": str(total("net_pnl") + total("fees") - spread),
                             "instant_edge_below_fee_fills": below}
            variants.append({"variant": label, "policy_overlay": {"entry_fee_buffer_bps": buffer},
                             "configuration": configuration, "aggregate": aggregate, "sessions": sessions})
        report = {"schema_version": 1, "split": "train", "held_out_splits_used": [], "capture_count": len(paths),
                  "model_sha256": artifact["model_sha256"], "metadata_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
                  "study_plan_sha256": hashlib.sha256(args.plan.read_bytes()).hexdigest(), "variants": variants,
                  "claim_status": "Same saved policy, explicit external rule overlay. In-sample development only; not retrained, independent validation or a profitable edge."}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps([{key: variant[key] for key in ("variant", "aggregate")} for variant in variants], indent=2))
        print(f"Report: {args.output}")
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
