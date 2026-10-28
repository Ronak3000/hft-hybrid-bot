# Phase 14: quote-grid economics and the fresh study

## Why this changes PPO logic

The old 1–5 tick width space cannot cover the v1 pilot's 0.1% per-fill fee by
symmetric spread capture at BTC prices. A separate abstention decision helps
exploration but does not repair this quote-range mismatch.

`QueueReplayEnv` now accepts an explicit ascending `half_spread_tick_choices`
grid. For example, widths `(1, 100, 1000, 6000, 10000)` require only five width
outputs in factorized schema 2, despite spanning 10,000 ticks. Width indices
map to these actual tick distances. No supplied grid preserves the old dense
`1..maximum_half_spread_ticks` mapping. The 14 observation fields remain the
same; the previous-action feature is normalized by the grid's action count.
Changing the grid therefore requires retraining, not editing an old sidecar.

Explicit grids contain at most 32 positive, strictly increasing integer widths
and stay within `maximum_half_spread_ticks`. Both held-out evaluators restore
the frozen grid. The paired seeded-random control samples the same grid;
fixed-spread and inventory-skew baseline widths remain separately declared
settings, not automatically selected using held-out outcomes.

The C++ matching engine is not involved in this change. The legacy dashboard's
training worker is also unchanged; these controls belong to the research CLI.

## Training preflight

`train_queue_ppo.py` now records an economic sanity check using only the first
applied depth-update feature from the first validated training capture. It
does not advance the Gymnasium environment's episode counter or read held-out
capture bytes. Its source hash and reference timestamp are recorded.

The check reports `2 * half_width * tick_size - 2 * fee * reference_mid`, per
base-asset unit. A nonpositive bid is not considered a usable fee-covering width.
It is same-mid, symmetric-round-trip arithmetic, assuming both sides fill.
It is not a forecast, a queue-depth sufficiency check, or a profitability test.
The reference may differ from later training prices. Zero fee and rebates are
explicit modeled scenarios, not silently substituted for costs.

- `--preflight-only` prints the report and creates no model or metadata file.
- `--require-fee-coverage` rejects a grid with no usable fee-covering width at
  that reference. Without it, a warning preserves old experiment compatibility.
- Successful training stores the report as `quote_economics_preflight` in the
  model sidecar and records the explicit grid in `configuration`.

Example *after collecting the new training split*, using the old fee assumption
for illustration only:

```powershell
python scripts/train_queue_ppo.py --plan data/studies/btcusdt-ppo-v2-activity-v1.json --tick-size 0.01 --quantity 0.001 --max-abs-inventory 0.01 --maker-fee-rate 0.001 --order-latency-ns 1000000 --cancel-latency-ns 1000000 --action-schema-version 2 --max-half-spread-ticks 10000 --half-spread-tick-choices 1 100 1000 6000 10000 --decision-interval-ns 250000000 --total-timesteps 102400 --seed 7 --preflight-only --require-fee-coverage --output engine/saved_models/btcusdt-v2-preflight.zip
```

This grid is an example, not a selected final configuration. Do not widen quotes
outside the captured book and claim exact fills: market-by-price L2 and bounded
snapshot depth still limit queue reconstruction. Confirm data coverage and the
modeled venue/account fee before freezing training candidates.

## Fresh collection plan

`data/studies/btcusdt-ppo-v2-activity-v1.json` seals 25 later chronological
sessions: 10 training, 5 validation, and 10 test, with 10,000 applied depth
deltas per session (250,000 planned total). There are no new captures yet.
Each session also requires at least 1,000 accepted public trades, no depth/trade
ID gaps, and at most two disconnects, with reconnect boundaries kept explicit.

The data plan freezes collection settings only. It is not a sealed algorithm
experiment, does not define an attainable fee tier, and does not permit tuning
against the consumed v1 final-test window. Session count alone does not establish
independence or coverage of different market conditions; spread collection
across suitable later windows and freeze the evaluation rule before validation.

Begin with:

```powershell
python scripts/capture_study_session.py --plan data/studies/btcusdt-ppo-v2-activity-v1.json --session-id train-001
```

Collect `train-001` through `train-010` in order. Then run the training-only
preflight, check data depth and fees, and freeze a small candidate grid with the
same three predetermined seeds. Keep final-test sessions sealed until the
selected candidate, baseline settings, and analysis rule are frozen.

No live collection or long training run is launched by creating this plan.
