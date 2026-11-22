# Project 1 — Limit order book prediction

**Question:** Do recent BTCUSDT order-book updates predict the direction of
the mid-price 10, 50, or 100 feature updates ahead?

[Shared capture and dataset setup](../../docs/lob-alpha.md) ·
[Prediction evaluator](../../scripts/evaluate_lob_alpha.py) ·
[Feature and model code](../../engine/research/lob_alpha.py)

Compare the training-majority class, microprice sign, and logistic regression.
Add `--lookback 8` to include a small two-hidden-layer MLP that reads eight
consecutive causal feature rows. All models in that report score the same
eligible rows. The MLP is a compact nonlinear baseline, not a DeepLOB
reproduction. Feature windows and labels never cross a snapshot segment.

Read class support and per-session macro-F1 alongside accuracy. A correct
mid-price direction is not an executable trade. Freeze any model selection on
validation, and measure subsequent behavior on fresh sessions.
