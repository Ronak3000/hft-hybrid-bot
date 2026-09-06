# Phase 2: leakage-safe labels and chronological splits

This stage prepares the causal L2 features for statistical research. It creates
future-return targets offline, then assigns rows to train, validation, and test
time intervals. It does not train a model.

## Why labels are separate from features

The feature at time `t` describes information already known at `t`. A return
after `t` is an answer the model is asked to predict, so it is stored only in a
column beginning with `label_`.

For a requested horizon `h`, the label builder finds the first observed feature
row in the same uninterrupted sequence segment whose event time is at least
`t + h`. The label is:

```text
label_mid_return_bps = (future_mid - current_mid) / current_mid * 10,000
```

The realized horizon is recorded because WebSocket updates are irregular. Rows
near the end of a segment are dropped when no valid future observation exists.
Labels never cross a sequence gap, disconnect/resnapshot boundary, or capture
segment.

Every label records its target timestamp, target update ID, target segment, and
realized horizon. These fields make the absence of look-ahead inspectable.

## Why random splitting is wrong here

Adjacent order-book observations are strongly related. Randomly shuffling them
would place nearly identical neighboring states in both training and test data.
That produces optimistic scores which are unlikely to survive live trading.

ApexHFT divides the complete event-time span into contiguous intervals:

```text
past                       future
|------ train ------|-- validation --|-- test --|
```

A training row is removed if its future-return target reaches the validation
boundary. A validation row is removed if its target reaches the test boundary.
This boundary purge prevents the label itself from leaking future partitions.

## One-command preparation

First build a feature file using the Phase 2 feature guide. Then run:

```bash
python scripts/prepare_l2_dataset.py \
  data/features/btcusdt-l5.csv \
  --horizon-ms 1000 \
  --train-ratio 0.6 \
  --validation-ratio 0.2 \
  --labeled-output data/features/btcusdt-l5-h1000-labels.csv \
  --output data/features/btcusdt-l5-h1000-split.csv
```

The remaining `0.2` is the test interval. Both outputs are overwrite-protected
and receive manifests containing hashes, schemas, parameters, row counts, and
upstream provenance.

The command verifies the finished split and warns if a short dataset leaves any
partition empty. Never train on a dataset with an empty partition.

## How the partitions should be used

- **Train:** fit the scaler, HMM parameters, and any learned strategy.
- **Validation:** choose feature sets, state counts, covariance form, and other
  hyperparameters.
- **Test:** evaluate the single frozen choice once. Do not tune after viewing it.

For the HMM, the scaler mean and variance must be calculated from `train` only.
Apply those frozen values to validation and test. HMM state numbers have no
inherent meaning; name regimes only after inspecting training-period state
statistics, and keep the fitted state mapping fixed out of sample.

## Tests and limitations

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Tests cover hand-calculated timestamp returns, irregular-horizon selection,
segment isolation, chronological ordering, boundary purging, invalid ratios,
provenance verification, and byte-identical repeated builds.

On 2026-09-06, the live five-event smoke capture completed the entire
capture-to-feature-to-label-to-split chain. Its validation interval was empty
after correct boundary purging, which is expected for such a tiny sample and is
why the command prints a warning. This smoke run verifies plumbing only; it is
not suitable for model fitting or performance claims.

This prepares trustworthy data, but it does not establish predictive power.
Confidence intervals, multiple capture days, several assets, transaction costs,
and queue-aware fills remain necessary before any trading-performance claim.
