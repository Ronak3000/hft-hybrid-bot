# Phase 5: real-capture baseline evaluation

This phase streams a verified L2/public-trade capture through the Phase 4
execution simulator. It implements two deterministic non-learning policies and
writes a source-linked JSON report. It does not train or evaluate PPO.

## Why the warmup boundary matters

The collector opens the WebSocket before requesting the REST snapshot. Some
WebSocket messages therefore have local receive timestamps earlier than the
snapshot response even though the snapshot record must appear first in the file
for reconstruction.

The runner handles this explicitly:

1. load the snapshot;
2. apply buffered depth messages received before the snapshot response;
3. count but do not trade on buffered public trades;
4. allow the policy to make its first decision only when reconstructed market
   time reaches the snapshot response time.

This prevents look-ahead and prevents quotes from filling on events that
occurred before the strategy could possess a synchronized book. After strategy
activation, a backward local timestamp is a hard error rather than silently
reordering events.

Depth gaps, trade-ID gaps, and disconnects invalidate all quotes and disable
trading until a fresh snapshot begins another segment.

## Implemented policies

### Fixed spread

The policy calculates the current visible mid, places bid/ask targets a fixed
number of ticks around it, and rounds outward to the configured tick grid. It
does not estimate alpha.

### Inventory skew

This policy starts from the same spread. Positive inventory moves both targets
lower, discouraging another buy and encouraging an inventory-reducing sell.
Negative inventory moves them higher. The skew is linear, bounded by the
configured inventory limit, and expressed in ticks.

Neither policy is claimed to be profitable or optimal.

## Run both baselines

Example for a BTCUSDT capture:

```bash
python scripts/evaluate_capture_baselines.py \
  data/captures/btcusdt-l2-trades.jsonl \
  --tick-size 0.01 \
  --quantity 0.001 \
  --half-spread-ticks 1 \
  --max-skew-ticks 2 \
  --initial-cash 100000 \
  --maker-fee-rate 0.0001 \
  --order-latency-ns 1000000 \
  --cancel-latency-ns 1000000 \
  --max-abs-inventory 0.01 \
  --markout-ms 100 1000 5000 \
  --output data/features/btcusdt-baselines.json
```

The output uses exclusive creation and refuses to overwrite an earlier report.
It records the source capture SHA-256, capture metadata, every configuration
value, final book digest, and metrics for both policies. Decimal values are
serialized as strings so JSON conversion does not introduce binary floating-
point changes.

The fee and latency above are examples, not assertions about a Binance account.
Research runs must record values appropriate to the intended venue, account
tier, network, and experiment.

## Reported metrics

- accepted fills and filled quantity;
- submitted quantity and quantity fill rate;
- turnover and maximum absolute inventory;
- canceled, rejected, invalidated, and still-open orders;
- signed fees, where positive is a cost and negative is a rebate;
- net marked-to-market P&L;
- gross P&L before fees (`net P&L + signed fees`);
- spread edge relative to the visible mid immediately before each fill;
- signed post-fill markout at each requested horizon.

A positive signed markout is favorable to the fill direction. For a buy it is
`(future mid - fill price) * quantity`; for a sell the sign is reversed.
Markouts without enough future data are left unobserved rather than filled with
zero.

## Real-data smoke result

On 2026-09-06, the Phase 3 BTCUSDT smoke capture was evaluated twice with the
example 1 ms order/cancel latency, 1 bp fee, 0.001 quantity, and 0.01 inventory
limit. Both JSON files had the same SHA-256, demonstrating byte-for-byte repeat
output from the same capture and configuration.

Each policy produced four simulated fills totaling 0.003 BTC. The fixed-spread
run reported approximately -0.0310 USDT net marked-to-market P&L: approximately
0.0240 USDT of configured fees and -0.0070 USDT gross P&L before fees. The
inventory-skew result was identical on this short window except for order and
fill-rate counts. These are connectivity/reproducibility observations from 20
applied depth deltas and 182 public trades—not evidence of expected performance,
statistical significance, or profitability.

## What remains before PPO

1. Collect multi-session data across different volatility and liquidity periods.
2. Add Avellaneda–Stoikov and seeded random baselines.
3. Run latency, fee, spread, quantity, and queue-model sensitivity grids.
4. Evaluate only with chronological splits and confidence intervals across
   independent sessions.
5. Design the Gymnasium observation/action interface around this tested runner,
   then compare PPO against every deterministic baseline on identical test data.

HMM remains optional and should not block these steps.
