# Phase 3: co-captured L2 and public trades

This stage supplies the real-market-data foundation for the execution
simulator. The collector subscribes to Binance Spot diff-depth and individual
trade streams through one combined WebSocket connection, while obtaining the
required depth snapshot over REST.

It does not modify the C++ matching-engine hot path.

## Beginner mental model

The L2 stream says how displayed quantities at price levels change. The trade
stream says that a public execution occurred at a price and size, and whether
the buyer was the maker. Together they provide substantially more evidence for
a fill model than candles do.

They still do not reveal the individual orders ahead of a hypothetical quote.
Therefore ApexHFT can build an explicit **queue-ahead approximation**, but it
must not claim exact exchange queue position or exact historical fills.

## Capture

From the repository root:

```bash
python scripts/capture_binance_l2.py \
  --symbol BTCUSDT \
  --events 1000 \
  --depth-limit 1000 \
  --output data/captures/btcusdt-l2-trades.jsonl
```

`--events` remains the number of successfully applied depth deltas, so old
commands retain their meaning. Every trade arriving before that stopping point
is also stored. The final counts can differ between runs because live markets
do not produce depth updates and trades at a fixed ratio.

Each JSONL record contains a local nanosecond receive timestamp and the original
combined-stream payload. The relative arrival order of WebSocket messages is
preserved. The REST snapshot is written before its buffered WebSocket messages
so deterministic replay can initialize the book; its own receive timestamp
still records when the HTTP response arrived.

## Integrity and gap rules

- Depth update IDs use the existing snapshot/bridge/stale/gap rules.
- Individual trade IDs are checked for duplicates, backward movement, and
  observed jumps within one connection.
- An observed jump is recorded as `trade_gap`. This is a data-quality
  diagnostic, not proof that every missing numeric ID should have appeared on
  this client.
- A reconnect begins a new segment and obtains a new depth snapshot. Trade-ID
  continuity is deliberately not inferred across that boundary.
- The capture and manifest remain exclusive-create and SHA-256 verified.

Replay reports accepted, duplicate, out-of-order, and gap-bearing public trade
counts alongside the depth results:

```bash
python scripts/replay_l2.py data/captures/btcusdt-l2-trades.jsonl
```

## Reproduction smoke check

On 2026-09-06, a local BTCUSDT run stopped after 20 applied depth deltas. The
sealed capture contained one snapshot, 22 depth messages (including two stale
buffered messages), and 182 public trades. Replay found no depth gap, trade-ID
gap, duplicate trade, out-of-order trade, or reconnect; the final book remained
synchronized. Mixed WebSocket receive timestamps were nondecreasing. The raw
file is ignored by Git and is a connectivity check, not a research dataset or a
performance/profitability result.

## Synchronization boundary

Using Binance's combined-stream transport preserves the order in which this
client receives messages. It does **not** make a depth update and a trade one
atomic exchange event. Exchange event timestamps and local receive timestamps
are retained so later experiments can define and audit their ordering policy.

The stored trades are public market executions. They are not fills of ApexHFT
orders, and buyer-maker direction is not a participant identity.

## Why this precedes PPO

PPO can only learn what its environment rewards. The next implementation should
therefore consume these verified records and model:

1. a quote's estimated displayed quantity ahead;
2. latency between decision, order arrival, cancellation, and observation;
3. trade-through and same-price depletion rules;
4. maker/taker fees and inventory/cash conservation;
5. mark-to-market, spread capture, fees, inventory drift, and adverse-selection
   P&L attribution.

Only after deterministic unit tests and simple policy baselines pass should PPO
training be changed. An HMM may later provide causal regime probabilities, but
it is optional and should be accepted only if it improves held-out results.

## Current limitations

- Binance Spot is the only implemented venue.
- No substantial multi-session dataset or published latency study exists yet.
- Local timestamps use the host wall clock; clock synchronization quality is
  not yet measured.
- Capture reconnects do not backfill trades missed while disconnected.
- The existing feature builder intentionally ignores trade records until a
  separately versioned trade-feature schema is designed.
- No live order routing or real-money execution is implemented or implied.

Protocol reference: [Binance Spot WebSocket Streams](https://developers.binance.com/zh-CN/docs/products/spot/testnet/web-socket-streams).
