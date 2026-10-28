"""Compare saved PPO candidates on training captures only, without performance claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.research.study_plan import validated_split_capture_paths
from engine.research.ppo_evaluation import load_ppo_artifact, _evaluate_capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--models", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError("comparison output already exists")
        training = validated_split_capture_paths(args.plan, "train", project_root=PROJECT_ROOT)
        loaded = [load_ppo_artifact(path, plan_path=args.plan, training_paths=training) for path in args.models]
        execution_fields = ("tick_size", "quantity", "initial_cash", "maker_fee_rate",
                            "order_latency_ns", "cancel_latency_ns", "max_abs_inventory", "decision_interval_ns")
        reference = loaded[0][0]["configuration"]
        for artifact, _ in loaded:
            if any(artifact["configuration"].get(key, 0) != reference.get(key, 0) for key in execution_fields):
                raise ValueError("candidates must share execution assumptions")
        import torch
        from stable_baselines3 import PPO
        torch.set_num_threads(1)
        models = []
        for metadata, (artifact, model_path) in zip(args.models, loaded):
            predictor = PPO.load(model_path, device="cpu")
            if predictor.num_timesteps != artifact["total_timesteps"]:
                raise ValueError("model budget does not match metadata")
            sessions = []
            for capture in training:
                print(f"Evaluating {model_path.stem}: {capture.stem}", flush=True)
                sessions.append(_evaluate_capture(predictor, capture, artifact["configuration"]))
            counts = {}
            for session in sessions:
                for segment in session["segments"]:
                    for mode, count in segment["action_counts"].items():
                        counts[mode] = counts.get(mode, 0) + count
            total = lambda key: sum((Decimal(session[key]) for session in sessions), Decimal("0"))
            models.append({
                "model_file": model_path.name, "model_sha256": artifact["model_sha256"],
                "metadata_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest(),
                "seed": artifact["seed"], "total_timesteps": artifact["total_timesteps"],
                "configuration": artifact["configuration"], "sessions": sessions,
                "aggregate": {"net_pnl": str(total("net_pnl")), "fees": str(total("fees")),
                              "turnover": str(total("turnover")), "fills": int(total("fills")),
                              "action_counts": counts},
            })
        report = {"schema_version": 1, "split": "train", "held_out_splits_used": [],
                  "study_plan_sha256": hashlib.sha256(args.plan.read_bytes()).hexdigest(),
                  "capture_count": len(training), "models": models,
                  "claim_status": "In-sample development diagnostics; not out-of-sample performance. Different budgets/configurations are confounded."}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps([{key: item[key] for key in ("model_file", "total_timesteps", "aggregate")} for item in models], indent=2))
        print(f"Report: {args.output}")
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
