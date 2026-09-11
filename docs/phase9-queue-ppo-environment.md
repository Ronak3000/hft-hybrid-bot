# Phase 9: queue-simulator-backed PPO environment

Phase 9 replaces the research path of the old candle-driven Gymnasium
environment. The new `QueueReplayEnv` consumes immutable L2/trade captures and
uses the exact same `QueueAwareSimulator` and quote-reconciliation function as
the deterministic baselines.

This phase establishes a credible learning environment. It does not demonstrate
that PPO learns a profitable policy or outperforms a baseline.

## Episode and causality rules

- One verified capture segment is one episode. Captures containing reconnects
  expose every snapshot-delimited segment in deterministic round-robin order;
  later valid segments are not silently discarded.
- Snapshot-time WebSocket records are warmup only. The agent cannot trade on
  information buffered before the REST snapshot completed.
- The agent acts after observing the current synchronized book.
- By default, a new decision occurs after each successfully applied depth
  delta. A frozen positive `decision_interval_ns` instead waits for the first
  applied delta at or after that interval while still processing every
  intervening market event.
- Public trades between decisions consume queue ahead and may fill orders.
- The chosen quote target persists between decisions and can replace a filled
  quote, subject to the same order and cancellation latency as every baseline.
- A depth gap, trade gap, disconnect, new snapshot segment, or end of capture
  truncates the episode. There is no fabricated drawdown loss or terminal bonus.

## Action space

The action is one discrete integer:

- action `0`: leave the market and cancel both sides;
- every other action: one combination of quote half-width and center skew in
  integer ticks.

Quotes are rounded outward to the tick grid. Width is at least one tick. The
simulator rejects marketable orders and suppresses inventory-increasing quotes
at the configured inventory boundary.

This bounded action space is intentionally easier to audit than continuous
gamma/spread controls whose economic meaning changes with price scale.

## Observation space

The 14 float32 features are causal and price-normalized:

1. spread in ticks;
2. Level-1 depth imbalance;
3. microprice displacement from mid in ticks;
4. last decision-to-decision mid change in ticks;
5. inventory divided by the hard inventory limit;
6. previous action normalized to `[0, 1]`;
7–10. bid open, active, normalized queue ahead, and cancel-pending state;
11–14. the same four fields for the ask.

Clipping bounds are part of the environment schema and avoid leaking the raw
BTCUSDT price scale into the policy.

## Reward

For consecutive decision times, the reward is:

```text
(change in marked net worth - inventory penalty) / reward scale

inventory penalty = coefficient
                  * (inventory / maximum inventory)^2
                  * elapsed seconds
```

Marked net worth includes cash, inventory, and configured maker fees through the
exact-decimal simulator. The penalty is an endpoint approximation over each
decision interval and is recorded in `info`. Set it before training and do not
tune it on the test split.

## Training-only command

After every planned training session passes the Phase 8 audit:

```bash
python scripts/train_queue_ppo.py \
  --plan data/studies/btcusdt-pilot-v1.json \
  --tick-size 0.01 \
  --quantity 0.001 \
  --max-abs-inventory 0.01 \
  --maker-fee-rate 0.0001 \
  --order-latency-ns 1000000 \
  --cancel-latency-ns 1000000 \
  --decision-interval-ns 250000000 \
  --inventory-penalty-per-second 0.01 \
  --total-timesteps 102400 \
  --seed 7 \
  --output engine/saved_models/queue-ppo-seed-7.zip
```

The command refuses an incomplete training split or any study containing
rejected data. It selects only paths assigned to `train`, writes a source-hash
and dependency-version sidecar, and explicitly records that no held-out split
was used.

The example parameters are experiment inputs, not recommended trading settings.
The decision interval is recorded in new sidecars; its zero default preserves
compatibility with PPO v1 artifacts.
Total timesteps must divide exactly into rollout length so the requested and
actual training budgets cannot silently differ. PPO architecture and optimizer
defaults are exposed as explicit command arguments and recorded in the sidecar.
Training enables deterministic PyTorch algorithms, defaults to one PyTorch CPU
thread, and records runtime/platform metadata. This reduces avoidable variation;
it does not promise bit-identical models across different hardware or libraries.
Begin with a short smoke run. Multiple seeds, validation-only configuration
assessment, and a frozen test comparison against all baselines are required
before any PPO performance statement is allowed.

## Legacy path

`TradingEnv` and the Celery worker remain for compatibility with the current UI,
but they are not the research environment. They still consume OHLCV-derived
synthetic events and must not be used for résumé claims about L2 PPO performance.
