# Phase 4: queue-aware paper execution core

This phase replaces the project's old “price touched my quote, therefore I
filled” assumption with a small deterministic execution model. It consumes the
validated `L2Book` and `MarketTrade` types from the real-data pipeline, but it
is not yet connected to Gymnasium or PPO.

The implementation is in `engine/simulation/queue_simulator.py`. It is separate
from the C++ matching-engine hot path.

## Beginner mental model

Suppose the visible bid is 100 with quantity 5. If ApexHFT submits another bid
at 100, it does not jump ahead of those 5 units. Its initial estimated
`queue_ahead` is therefore 5.

If a seller-initiated public trade executes 4 units at 100, ApexHFT estimates
that one unit remains ahead. If the next seller-initiated trade executes 2
units at 100, the first unit consumes the estimated queue and only the remaining
one unit can fill ApexHFT's quote.

This is an approximation because Binance Spot L2 is market-by-price rather than
market-by-order. The feed cannot identify the exact individual orders ahead or
behind a hypothetical ApexHFT order.

## Implemented rules

- Prices, quantities, cash, fees, inventory, and net worth use `Decimal` with a
  fixed 50-digit calculation context.
- A submission becomes active only after `order_latency_ns`.
- A cancellation becomes effective only after `cancel_latency_ns`; a trade may
  fill the quote while cancellation is in flight.
- Activation uses the book visible when the order reaches the simulated venue.
- A quote that would cross the opposite best price is rejected because this
  simulator currently models maker orders, not taker execution.
- One open bid and one open ask are allowed. This keeps quote replacement and
  latency behavior unambiguous for the first market-making baseline.
- Displayed quantity already present at the exact quote price becomes initial
  queue-ahead.
- Only correctly directed public trades at that price consume queue-ahead.
- Displayed L2 quantity reductions receive no queue credit. This conservative
  rule avoids assuming that unknown cancellations occurred ahead of ApexHFT.
- A correctly directed trade through the quote fills its remaining quantity,
  subject to the inventory limit. This is a counterfactual inference: a real
  resting quote would have changed the historical matching path.
- Positive fee rates are costs and negative rates are rebates. Both remain
  configurable because venue/account fee schedules can change.
- Fill records contain the simulated order, public trade ID, local receive
  timestamp, exchange trade timestamp, price, quantity, notional, and fee.
- A data gap or disconnect immediately invalidates pending and active quotes;
  the simulator never carries them across unknown market history.

## Accounting identities

For a buy of quantity `q` at quote price `p` with signed fee `f`:

```text
cash change      = -(p * q) - f
inventory change = +q
```

For a sell:

```text
cash change      = +(p * q) - f
inventory change = -q
```

Turnover is the sum of absolute fill notionals. Net worth at mark `m` is:

```text
cash + inventory * m
```

Tests verify these equations, inventory caps, partial fills, fee rebates,
latency races, passive-order rejection, queue consumption, gap invalidation,
and independence from the process-wide Decimal precision.

## Run the tests

From the repository root:

```bash
python -m unittest tests.test_queue_simulator -v
```

These tests are deterministic and require no network connection or C++ Python
extension.

## What remains before PPO

1. The full-capture runner and the fixed-spread/inventory-skew policies are now
   implemented in [the Phase 5 guide](phase5-capture-baselines.md).
2. Add Avellaneda–Stoikov and random policies on exactly the same event stream.
3. Attribute P&L into spread capture, signed fees/rebates, inventory mark-to-
   market, and post-fill adverse selection at fixed time horizons.
4. Add quote uptime, fill rate, turnover, inventory distribution, rejection
   counts, and latency-sensitivity reports.
5. Validate the simulator on chronological train/validation/test periods before
   changing PPO observations, actions, or rewards.

The HMM remains optional. A regime feature should be added only after these
baselines work and only if it improves held-out results without leakage.
