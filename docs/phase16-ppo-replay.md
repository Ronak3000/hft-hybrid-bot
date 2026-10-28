# PPO in the working replay

## Demo training configuration (declared before this run)

This integration run is one seed, not the final multi-seed research study.
It uses only the ten validated training captures in
`btcusdt-ppo-v2-activity-v1`. No validation or test capture is used to select
settings, train, export the demonstration, or claim performance.

- PPO seed 7; 16,384 environment steps; CPU; one deterministic PyTorch thread.
- Two 64-unit Tanh layers, learning rate 0.0003, entropy coefficient 0.001.
- Rollouts of 2,048 steps, minibatches of 64, 10 optimization epochs.
- Discount 0.99, GAE lambda 0.95, clipping 0.2.
- Factorized actions: quote/stay out, width index, skew index.
- Width choices 1, 100, 1,000, 8,000, 10,000 ticks; skew range ±2 ticks.
- Tick 0.01, quantity 0.001 BTC, inventory cap 0.01 BTC.
- Modeled maker fee 0.001 per fill, 1 ms order/cancel latency.
- Decision target 1 second, reward scale 0.01, inventory penalty 0.01 per second.

The initial snapshot of each training capture has visible price range covering
a 100-unit half width in both directions. This is an initial coverage sanity
check, not proof of exact queue position or complete depth coverage throughout
each recording. The one-second interval is an activity-control candidate,
not a validated improvement.

Training command, from the repository root with PyTorch and Stable-Baselines3
installed in the selected Python environment:

```powershell
python scripts/train_queue_ppo.py --plan data/studies/btcusdt-ppo-v2-activity-v1.json --tick-size 0.01 --quantity 0.001 --max-abs-inventory 0.01 --maker-fee-rate 0.001 --order-latency-ns 1000000 --cancel-latency-ns 1000000 --action-schema-version 2 --max-half-spread-ticks 10000 --half-spread-tick-choices 1 100 1000 8000 10000 --max-absolute-skew-ticks 2 --decision-interval-ns 1000000000 --reward-scale 0.01 --inventory-penalty-per-second 0.01 --entropy-coefficient 0.001 --total-timesteps 16384 --seed 7 --device cpu --require-fee-coverage --output engine/saved_models/btcusdt-v2-demo-seed-7-16384.zip
```

The saved model and sidecar remain local and ignored by Git. The sidecar binds
the model hash, study hash, all training capture hashes, configuration,
dependencies, and actual training budget. Do not edit it to change an existing
model's action space or execution assumptions.

## Replay integration

The exporter accepts an optional `--ppo-metadata` sidecar. It verifies the
artifact and source identities before loading the model. Predictions are made
causally from the current observation and sent through `env.step`; baseline
targets use `env.step_quote_target` on the same execution environment.

The browser plays precomputed model outputs; it does not execute PyTorch or
download the model weights. Model identity, seed, budget, and last sampled PPO
decision are visible. A training replay is not out-of-sample evaluation.

All exported controls use the model's fee, latency, size, inventory limits,
and decision interval. The original narrow fixed/inventory controls remain
reference policies. A widest-grid fixed control is included alongside no-quote
to expose any benefit that simply comes from reducing activity or widening
quotes. These are descriptive training illustrations, not a policy ranking.

```powershell
python scripts/export_replay_demo.py --plan data/studies/btcusdt-ppo-v2-activity-v1.json --ppo-metadata engine/saved_models/btcusdt-v2-demo-seed-7-16384.json
```

## Completed integration run

Training completed at 16,384 steps, seed 7. The model SHA-256 is
`f749f4ae61a6c7c4fb78a739873ae9cc07ddc5747ce7d87a03653e8aaf8019f9`.
Metadata SHA-256 is
`446c803cd5ca29def2b66e5c26be866e4b061bee410da93b57ba5f8f80477b99`.
Local model/metadata are ignored by Git; their identities accompany the public
replay outputs. Another training run may produce different bytes depending
on dependency/platform versions; do not claim bitwise cross-platform identity.

Displayed recordings were selected by first/last training ordinal, not P&L.
Fee-inclusive net P&L below is in USDT, with fills in parentheses:

| Policy | train-001 | train-010 |
| --- | ---: | ---: |
| PPO v2 | 0.0000 (0) | 0.0000 (0) |
| Inventory skew | -16.0562 (178) | -16.7302 (157) |
| Fixed spread | -16.0555 (183) | -16.7926 (157) |
| No quote | 0.0000 (0) | 0.0000 (0) |
| Fixed, widest grid | 0.0000 (0) | 0.0000 (0) |

PPO mostly abstains and occasionally requests 10,000-tick half-width quotes.
It earns no trading profit and produces no fills here. This demonstrates a
working model-to-execution-to-UI path, not successful market making or an
improvement over stronger baselines. The two activity controls also return zero.
No validation or test capture was opened. Next research work should address
the fee/activity trade-off using training data before freezing a multi-seed
configuration for validation; do not add a reward for gratuitous trading or
lower fees just to make this chart look profitable.
