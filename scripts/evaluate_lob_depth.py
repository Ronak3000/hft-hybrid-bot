"""Train depth models on real L2 windows and score chronological holdouts."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.research.lob_alpha import DEFAULT_HORIZONS, _score
from engine.research.lob_depth import DepthWindows, load_depth_session, validate_depth_splits


def _metrics(dataset, predicted):
    actual = [label - 1 for _, _, label in dataset.items]
    full = _score(actual, [label - 1 for label in predicted])
    sessions = {}
    for i, session in enumerate(dataset.sessions):
        subset = [j for j, (index, _, _) in enumerate(dataset.items) if index == i]
        sessions[session.path.name] = _score(
            [actual[j] for j in subset], [predicted[j] - 1 for j in subset],
        )
    return {"pooled": full, "sessions": sessions}


def run(args):
    import torch
    from torch import nn
    from torch.utils.data import DataLoader
    from engine.research.lob_deep_models import make_depth_model

    torch.set_num_threads(args.threads)
    torch.use_deterministic_algorithms(True)
    splits = {name: [load_depth_session(path, args.levels) for path in getattr(args, name)]
              for name in ("train", "validation", "test")}
    validate_depth_splits(splits)
    report = {
        "torch_version": torch.__version__, "levels": args.levels, "lookback": args.lookback,
        "seed": args.seed, "batch_size": args.batch_size, "epochs": args.epochs,
        "class_order": ["down", "flat", "up"], "purpose": args.purpose,
        "sessions": {
            name: [{"capture": s.path.name, "capture_sha256": s.source_sha256,
                    "full_depth_rows": len(s.groups), "first_receive_ns": s.first_receive_ns,
                    "last_receive_ns": s.last_receive_ns, "venue": s.venue, "symbol": s.symbol}
                   for s in sessions] for name, sessions in splits.items()
        },
        "horizons": {},
    }
    weights = {}
    for horizon in args.horizons:
        windows = {name: DepthWindows(sessions, args.lookback, horizon)
                   for name, sessions in splits.items()}
        training_labels = [label for _, _, label in windows["train"].items]
        if len(set(training_labels)) < 2:
            raise ValueError(f"horizon {horizon}: training requires at least two classes")
        majority = max((0, 1, 2), key=lambda c: (training_labels.count(c), -abs(c - 1), -c))
        result = {
            "split_rows": {name: len(window) for name, window in windows.items()},
            "controls": {
                split: {
                    "majority": _metrics(data, [majority] * len(data)),
                    # Sign of microprice minus mid equals sign of bid size minus ask size.
                    "microprice_sign": _metrics(data, [
                        1 + int(s.ladders[end, 1] > s.ladders[end, 3])
                          - int(s.ladders[end, 1] < s.ladders[end, 3])
                        for index, end, _ in data.items for s in (data.sessions[index],)
                    ]),
                }
                for split, data in windows.items() if split != "train"
            },
            "models": {},
        }
        for name in args.models:
            torch.manual_seed(args.seed)
            model = make_depth_model(name, args.levels, args.lookback)
            optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
            loader = DataLoader(windows["train"], batch_size=args.batch_size, shuffle=True,
                                generator=torch.Generator().manual_seed(args.seed))
            loss_fn = nn.CrossEntropyLoss()
            best = None
            best_f1 = -1

            @torch.inference_mode()
            def score(split):
                model.eval()
                predictions = []
                for x, _ in DataLoader(windows[split], batch_size=args.batch_size):
                    predictions.extend(model(x).argmax(dim=1).tolist())
                return _metrics(windows[split], predictions)

            for epoch in range(1, args.epochs + 1):
                model.train()
                for x, y in loader:
                    optimizer.zero_grad(set_to_none=True)
                    loss = loss_fn(model(x), y)
                    if not torch.isfinite(loss):
                        raise ValueError(f"{name}: non-finite training loss at horizon {horizon}")
                    loss.backward()
                    optimizer.step()
                validation = score("validation")
                f1 = validation["pooled"]["macro_f1"]
                if f1 > best_f1:
                    best_f1 = f1
                    best = epoch, deepcopy(model.state_dict()), validation
            epoch, state, validation = best
            model.load_state_dict(state)
            result["models"][name] = {"selected_epoch": epoch, "validation": validation,
                                      "test": score("test")}
            if args.weights:
                weights[f"{name}:{horizon}"] = state
        report["horizons"][str(horizon)] = result
    if args.weights:
        args.weights.parent.mkdir(parents=True, exist_ok=True)
        with args.weights.open("xb") as output:
            torch.save({"levels": args.levels, "lookback": args.lookback, "states": weights}, output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("train", "validation", "test"):
        parser.add_argument(f"--{name}", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--levels", type=int, default=10)
    parser.add_argument("--lookback", type=int, default=100)
    parser.add_argument("--horizons", nargs="+", type=int, default=DEFAULT_HORIZONS)
    parser.add_argument("--models", nargs="+", choices=("deeplob", "cnn-lstm", "transformer"),
                        default=("deeplob", "cnn-lstm", "transformer"))
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--purpose", choices=("development", "frozen-evaluation"), default="development")
    args = parser.parse_args()
    if min(args.horizons) < 1 or len(set(args.horizons)) != len(args.horizons):
        parser.error("horizons must be distinct positive integers")
    if min(args.epochs, args.batch_size, args.threads) < 1 or args.seed < 0:
        parser.error("epochs, batch size, and threads must be positive; seed must be nonnegative")
    if args.output.exists() or (args.weights and (
        args.weights.exists() or args.weights.resolve() == args.output.resolve()
    )):
        parser.error("use distinct, previously unused output paths")
    try:
        report = run(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, allow_nan=False)
            output.write("\n")
    except ModuleNotFoundError as exc:
        if exc.name != "torch":
            raise
        parser.error("PyTorch is required; see research/01-lob-prediction/README.md")
    except (OSError, ValueError, ArithmeticError) as exc:
        parser.error(str(exc))
    print(f"Depth model report: {args.output}")


if __name__ == "__main__":
    main()
