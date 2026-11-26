# Project 1 — Limit order book prediction

**Question:** Do recent BTCUSDT order-book updates predict the direction of
the mid-price 10, 50, or 100 feature updates ahead?

[Shared capture and dataset setup](../../docs/lob-alpha.md) ·
[Prediction evaluator](../../scripts/evaluate_lob_alpha.py) ·
[Feature and model code](../../engine/research/lob_alpha.py)

[Read the five-session pilot results](../pilot-2026-11-22.md#project-1--prediction).

Compare the training-majority class, microprice sign, and logistic regression.
Add `--lookback 8` to include a small two-hidden-layer MLP that reads eight
consecutive causal feature rows. All models in that report score the same
eligible rows. The MLP is a compact nonlinear baseline, not a DeepLOB
reproduction. Feature windows and labels never cross a snapshot segment.

Read class support and per-session macro-F1 alongside accuracy. A correct
mid-price direction is not an executable trade. Freeze any model selection on
validation, and measure subsequent behavior on fresh sessions.

## Multi-level depth models

The depth runner reads verified raw captures directly and builds 100-update
windows of the 10 best bid/ask prices and sizes. It excludes pre-snapshot
updates and never fills in missing depth; windows and targets stop at gaps
and shallow intervals. It compares a [DeepLOB-style network](https://arxiv.org/abs/1808.03668),
a separate temporal CNN–LSTM, and a Transformer with two simple controls on
identical 10/50/100-update labels. This is a Binance adaptation, not a
reproduction of the paper's original dataset or results.

Install the CPU PyTorch build in an activated development environment:

```powershell
python -m pip install -r requirements-alpha.txt
python -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
python scripts/evaluate_lob_depth.py --train data/captures/train-01.jsonl --validation data/captures/validation-01.jsonl --test data/captures/test-01.jsonl --epochs 1 --output data/features/depth-development.json --weights data/features/depth-development.pt
```

Use multiple chronological captures per split for a study. The runner fits
on training only and chooses a checkpoint by validation macro-F1 for each
model and horizon. A one-epoch run validates plumbing, not performance.
The Research tab shows the neural-model development benchmark. Its interactive
replay still shows the earlier logistic demo; it does not replay the neural runs.
