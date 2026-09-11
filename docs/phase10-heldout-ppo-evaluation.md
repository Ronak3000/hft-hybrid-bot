# Phase 10: held-out multi-seed PPO evaluation

Phase 10 adds the first integrity-checked held-out evaluator for models trained
by `train_queue_ppo.py`. It makes evaluation reproducible; it does not create a
positive PPO result, prove profitability, or complete the comparison with the
four frozen deterministic baselines.

## What the evaluator refuses

Before loading a policy, it verifies:

- the study plan has not changed byte-for-byte;
- every declared training capture and SHA-256 matches the plan;
- the model ZIP matches the byte count and SHA-256 in its sidecar;
- held-out data was not declared as training input;
- all models have unique seeds and one identical frozen configuration;
- the selected split is complete and passes its predeclared quality rules;
- validation is complete before test data can be opened.

The split-scoped audit stops reading at the requested chronological boundary.
Training therefore opens only training captures, validation opens training plus
validation, and only an explicitly confirmed final-test run opens test bytes.

Test evaluation additionally requires `--confirm-final-test`. Outputs use
exclusive creation so an existing report is not silently overwritten.

## Reconnect handling

Every snapshot-delimited segment in a verified capture is a separate Gymnasium
episode. Segment indices are deterministic. A reconnect, sequence gap, trade
gap, or new snapshot ends the current episode, and the next reset advances to
the next real segment rather than replaying segment zero forever.

P&L is reported per segment and summed per capture session. This makes the reset
boundary explicit. A later paired-baseline report must use the same segment
reset rule; do not compare these totals with a baseline report that carries
inventory across reconnects.

## Beginner workflow

Do not use the test captures while choosing hyperparameters.

1. Finish collecting and auditing the planned training and validation sessions.
2. Choose the PPO architecture, reward, latency, fees, action bounds, and a set
   of seeds before reading validation results.
   The pilot freezes these choices in
   `data/studies/btcusdt-pilot-v1-ppo-experiment.json`; its adjacent manifest
   seals the exact bytes.
3. Train at least three seeds with otherwise identical arguments. For example,
   run the Phase 9 training command for seeds `7`, `19`, and `43`, changing only
   `--seed` and `--output`.
4. Evaluate all predetermined seeds on validation:

```bash
python scripts/evaluate_queue_ppo.py \
  --plan data/studies/btcusdt-pilot-v1.json \
  --split validation \
  --calibration data/features/btcusdt-pilot-v1-as-calibration.json \
  --models \
    engine/saved_models/queue-ppo-seed-7.json \
    engine/saved_models/queue-ppo-seed-19.json \
    engine/saved_models/queue-ppo-seed-43.json \
  --output data/features/btcusdt-pilot-v1-ppo-validation.json
```

The `--models` arguments are metadata sidecars, not ZIP paths. The evaluator
finds and verifies the adjacent ZIP automatically. Stable-Baselines3 inference
runs on CPU with deterministic action selection.

5. Freeze the complete experiment configuration. Do not pick the luckiest seed
   and describe it as typical performance.
6. Only after the decision is frozen, run the test split once:

```bash
python scripts/evaluate_queue_ppo.py \
  --plan data/studies/btcusdt-pilot-v1.json \
  --split test \
  --calibration data/features/btcusdt-pilot-v1-as-calibration.json \
  --models \
    engine/saved_models/queue-ppo-seed-7.json \
    engine/saved_models/queue-ppo-seed-19.json \
    engine/saved_models/queue-ppo-seed-43.json \
  --confirm-final-test \
  --output data/features/btcusdt-pilot-v1-ppo-final-test.json
```

## Statistical interpretation

The report first averages P&L across predetermined training seeds within each
capture session. Sessions—not individual book updates—are the independent unit.
It then reports the sample standard deviation and a deterministic percentile
bootstrap interval across sessions. With only one validation session, no
dispersion or confidence interval is reported. Two test sessions produce an
interval, but that sample remains very small and must be described as a pilot.

The evaluator generates one paired report comparing the PPO seed average with
fixed-spread, inventory-skew, seeded-random, and frozen Avellaneda–Stoikov
policies. Every policy uses the same queue environment, snapshot-segment resets,
fees, latency, inventory limits, and capture bytes. Paired intervals resample
complete sessions. Until the real study is run, the résumé should claim the
research infrastructure—not PPO outperformance.
