"""Export a compact browser summary of source-matched development runs."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean


def summarize(depth, hawkes, fills, rl):
    test = depth["sessions"]["test"]
    hashes = [s["capture_sha256"] for s in test]
    if (hashes != [s["sha256"] for s in hawkes["test"]]
            or hashes != [s["sha256"] for s in fills["sessions"]["test"]]
            or any(hashes != run["sessions"]["test"] for run in rl["runs"])):
        raise ValueError("all reports must describe the same chronological test captures")
    paired = []
    for index, capture in enumerate(test):
        for algorithm in ("ppo", "sac"):
            modes = {}
            for mode in ("off", "on"):
                runs = [run for run in rl["runs"] if run["fill_signal"]["mode"] == mode]
                if sorted(run["seed"] for run in runs) != sorted(rl["seeds"]):
                    raise ValueError("expected both feature arms for every seed")
                records = [run["policies"][algorithm]["test"][index] for run in runs]
                if any(s["sha256"] != hashes[index] for s in records):
                    raise ValueError("RL policy output does not match the capture order")
                matched = [run["policies"].get(f"inventory_skew_matched_to_{algorithm}", {}).get("test")
                           for run in runs]
                if any(rows and rows[index]["sha256"] != hashes[index] for rows in matched):
                    raise ValueError("size-matched policy output does not match the capture order")
                modes[mode] = {
                    "pnl": mean(float(s["net_pnl"]) for s in records),
                    "fills": mean(s["fills"] for s in records),
                    "matchedPnl": mean(float(rows[index]["net_pnl"]) for rows in matched)
                    if all(matched) else None,
                }
            paired.append({"capture": capture["capture"], "algorithm": algorithm.upper(), **modes})
    return {
        "purpose": "development; reused test captures, not new evidence of outperformance",
        "captures": [{"file": s["capture"], "sha256": s["capture_sha256"]} for s in test],
        "lookback": depth["lookback"], "levels": depth["levels"], "depthEpochs": depth["epochs"],
        "depth": [
            {"horizon": int(horizon), "rows": result["split_rows"]["test"],
             "macroF1": {
                 **{name: info["pooled"]["macro_f1"] for name, info in result["controls"]["test"].items()},
                 **{name: info["test"]["pooled"]["macro_f1"] for name, info in result["models"].items()},
             }}
            for horizon, result in depth["horizons"].items()
        ],
        "arrival": [{"capture": s["capture"],
                     "hawkes": s["hawkes_log_likelihood_per_trade"],
                     "poisson": s["poisson_log_likelihood_per_trade"]} for s in hawkes["test"]],
        "fill": [{"name": name, "brier": value["brier"], "logLoss": value["log_loss"],
                  "rows": value["rows"], "fills": value["fills"]}
                 for name, value in fills["pooled_test"].items()],
        "seeds": rl["seeds"], "rlSteps": rl["runs"][0]["requested_steps"], "paired": paired,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("depth", "hawkes", "fills", "rl", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = {name: getattr(args, name).read_bytes() for name in ("depth", "hawkes", "fills", "rl")}
        parsed = {name: json.loads(data) for name, data in raw.items()}
        hashes = {name: sha256(data).hexdigest() for name, data in raw.items()}
        if any(run["fill_signal"]["report_sha256"] != hashes["fills"] for run in parsed["rl"]["runs"]):
            raise ValueError("the RL runs do not reference this fill forecast report")
        report = summarize(parsed["depth"], parsed["hawkes"], parsed["fills"], parsed["rl"])
        report["sourceReportSha256"] = hashes
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as dest:
            json.dump(report, dest, indent=2, allow_nan=False)
            dest.write("\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Research summary: {args.output}")


if __name__ == "__main__":
    main()
