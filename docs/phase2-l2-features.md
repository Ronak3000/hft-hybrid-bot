# Phase 2: causal L2 feature dataset

This stage converts a verified Level-2 capture into a deterministic CSV for
research. It is deliberately separate from the capture file: raw venue payloads
remain unchanged, while derived datasets can be rebuilt whenever formulas or
parameters change.

## The beginner rule: information must flow forward in time

At update `t`, a valid feature may use the snapshot and deltas observed up to
and including `t`. It must not use a price, fill, statistic, normalization
constant, or fitted model parameter from `t + 1` or later.

The current output contains no forward-return column. When supervised labels
are added later, their names will begin with `label_` and they will never be
included in the model input list.

## Features

Each applied, sequence-valid delta produces one row:

- `best_bid`, `best_ask`, `mid_price`, and quoted `spread`;
- `spread_bps`, normalized by the current mid;
- best-level quantities;
- `microprice`, which shifts the mid toward the side with less opposing depth;
- `microprice_deviation_bps` from the current mid;
- bid and ask depth summed over a configurable number of levels;
- normalized depth imbalance `(bid_depth - ask_depth) / total_depth`;
- Level-1 order-flow imbalance (`ofi_l1`) from the previous valid state;
- counts of changed bid and ask levels;
- venue event time, local receive time, and update ID for auditing.

Stale events produce no row. A sequence gap invalidates feature history. After
a new snapshot, OFI starts from that snapshot rather than comparing states
across missing data.

All calculations use an explicit 50-digit decimal context. This prevents an
unrelated library from changing Python's global decimal precision and silently
changing the dataset.

## Build a feature file

From the repository root:

```bash
python scripts/build_l2_features.py \
  data/captures/btcusdt-example.jsonl \
  --levels 5 \
  --output data/features/btcusdt-example-l5.csv
```

The output path must be new. The accompanying manifest records:

- feature schema version and ordered columns;
- depth-level configuration;
- row and byte counts;
- feature-file SHA-256;
- source capture SHA-256 and capture metadata.

Therefore an experiment can prove both the raw capture it used and the exact
derived file it consumed. The hash detects changes relative to the manifest; it
is not a digital signature against replacement of both files.

## Formulas worth understanding for interviews

For best bid `b`, best ask `a`, bid quantity `q_b`, and ask quantity `q_a`:

```text
mid        = (b + a) / 2
microprice = (a*q_b + b*q_a) / (q_b + q_a)
imbalance  = (bid_depth - ask_depth) / (bid_depth + ask_depth)
```

For OFI, a higher bid contributes the new bid quantity, a lower bid removes the
old bid quantity, and an unchanged bid contributes its quantity change. The ask
side is symmetric with the sign reversed. Positive OFI represents net pressure
toward the ask; it is a feature, not proof that the next price move is positive.

## Tests

```bash
python -m unittest discover -s tests -p "test_l2_*.py" -v
```

The feature tests use hand-calculated books, check stale and gap behavior,
change global decimal precision, rebuild the same dataset twice, and verify that
the bytes and source linkage are identical.

## Reproduction smoke check

On 2026-09-06, the complete live path captured five BTCUSDT deltas, generated
five Level-5 feature rows, and verified both manifests back to the recorded
Binance Spot source metadata. The raw and derived smoke files are intentionally
ignored by Git. This verifies the pipeline wiring; five observations are not a
research sample and support no predictive claim.

## What this does not prove

- It does not show that imbalance or microprice predicts returns.
- It does not model queue position or fills.
- It does not account for fees, latency, or inventory.
- It does not make an HMM profitable or meaningful by itself.

The next research step is a timestamp-based label builder and chronological
train/validation/test splitter. After those are tested, the HMM can be fitted on
training-only standardized features and evaluated as a regime model.
