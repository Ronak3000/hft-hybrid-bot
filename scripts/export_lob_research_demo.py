"""Bundle derived, source-linked L2 pilot data for the offline Research UI."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.research.lob_alpha import (
    CLASSES, DEFAULT_HORIZONS, INPUTS, fit_direction_model, load_session, validate_splits,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for split in ("train", "validation", "test"):
        parser.add_argument(f"--{split}", nargs="+", type=Path, required=True)
    parser.add_argument("--quote-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    splits = {name: [load_session(path) for path in getattr(args, name)]
              for name in ("train", "validation", "test")}
    validate_splits(splits)
    metadata = splits["train"][0].manifest["source_metadata"]
    if metadata["venue"] != "binance_spot":
        parser.error("this demo supports Binance Spot feature exports only")
    quotes = json.loads(args.quote_report.read_text(encoding="utf-8"))
    if quotes.get("schema_version") != 3 or any(
        "symmetric_widened" not in item for item in quotes.get("sessions", [])
    ):
        parser.error("regenerate the quote report with the three-policy evaluator")
    if [item["feature_sha256"] for item in quotes["sessions"]] != [
        item.manifest["sha256"] for item in splits["test"]
    ]:
        parser.error("quote report does not match the requested test features")
    if any(item["training_feature_sha256"] != [s.manifest["sha256"] for s in splits["train"]]
           or item["validation_feature_sha256"] != [s.manifest["sha256"] for s in splits["validation"]]
           for item in quotes["sessions"]):
        parser.error("quote report does not match the requested train/validation features")
    demo = {
        "schema": 1, "symbol": metadata["symbol"],
        "venue": "Binance Spot", "horizons": DEFAULT_HORIZONS,
        "quoteReport": quotes, "sessions": [],
    }
    models = {h: fit_direction_model(splits["train"], h) for h in DEFAULT_HORIZONS}
    for session in splits["test"]:
        features = [tuple(float(row[name]) for name in INPUTS) for row in session.rows]
        forecasts = [model.predict(features).tolist() for model, _ in models.values()]
        majority = [max(CLASSES, key=lambda label: (y.count(label), -abs(label), -label))
                    for _, y in models.values()]
        frames = []
        for row, prediction in zip(session.rows, zip(*forecasts, strict=True), strict=True):
            values = [float(row[key]) for key in ("mid_price", *INPUTS)]
            if not all(math.isfinite(value) for value in values):
                parser.error(f"non-finite replay value in {session.name}")
            frames.append([int(row["received_time_ns"]) // 1_000_000, int(row["segment_id"]),
                           *values, *prediction])
        demo["sessions"].append({
            "name": session.name, "featureSha256": session.manifest["sha256"],
            "captureSha256": session.manifest["source_sha256"],
            "majority": majority, "frames": frames,
        })
    captures = [s.manifest["source_metadata"].get("captured_at_utc") for s in splits["test"]]
    demo["snapshot"] = min(date[:10] for date in captures if date) if all(captures) else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(demo, separators=(",", ":"), allow_nan=False) + "\n")
    print(f"Exported {len(demo['sessions'])} recorded test sessions to {args.output}")


if __name__ == "__main__":
    main()
