# Phase 6: model-based, random, and sensitivity baselines

This phase completes the initial non-PPO comparison set with a seeded-random
control and a finite-horizon Avellaneda–Stoikov approximation. It also adds a
bounded grid runner for testing whether conclusions survive different fee,
latency, and quote-width assumptions.

## Seeded-random control

The random policy samples its quote half-width and center skew in integer ticks.
It uses an embedded SplitMix64 generator with an explicit seed. It does not use
Python's global random state, so unrelated code cannot change the action
sequence.

Random is a negative-control baseline, not a plausible production strategy. A
learned policy that cannot reliably outperform it out of sample has not
demonstrated useful learning.

## Avellaneda–Stoikov approximation

For mid-price `s`, inventory `q`, risk aversion `gamma`, volatility `sigma`,
remaining horizon `tau`, and exponential arrival-decay parameter `k`, the
implemented finite-horizon approximation is:

```text
reservation price = s - q * gamma * sigma^2 * tau

total spread = gamma * sigma^2 * tau
             + (2 / gamma) * ln(1 + gamma / k)
```

The bid and ask are centered around the reservation price and rounded outward
to the configured tick grid. Positive inventory lowers the reservation price.
As the remaining horizon reaches zero, the inventory-risk term vanishes while
the arrival-intensity term remains.

This follows equations (29) and (30) of Marco Avellaneda and Sasha Stoikov,
[“High-frequency trading in a limit order book”](https://math.nyu.edu/inmemoriam/avellaneda/HighFrequencyTrading.pdf),
*Quantitative Finance* 8(3), 2008.

### Units and calibration

The parameters cannot be copied blindly between assets or sampling clocks:

- `q` is base-asset inventory;
- `sigma` is mid-price volatility in quote currency per square root second;
- `tau` is seconds remaining in the configured policy session;
- `gamma` has inverse quote-currency units;
- `k` has inverse quote-currency units under the assumed exponential fill model.

The command-line defaults are smoke-test values, not fitted BTCUSDT parameters.
A research run must estimate volatility and arrival decay on training data only,
freeze them, and evaluate later chronological periods. The current simulator's
queue-aware observed fills replace the paper's Poisson simulation, so this is a
model-based quoting baseline rather than a reproduction of the paper's complete
market model.

## Four-policy report

`scripts/evaluate_capture_baselines.py` now evaluates:

1. fixed spread;
2. inventory skew;
3. seeded random;
4. Avellaneda–Stoikov.

The report schema is version 2 and records every random and model parameter.
Example additions to the Phase 5 command are:

```bash
--random-seed 7 \
--as-risk-aversion 0.001 \
--as-volatility 0.5 \
--as-intensity-decay 1 \
--as-session-horizon-seconds 60
```

## Sensitivity grid

Run a small grid on exactly the same capture:

```bash
python scripts/run_sensitivity_grid.py \
  data/captures/btcusdt-l2-trades.jsonl \
  --tick-size 0.01 \
  --quantity 0.001 \
  --fee-rates 0 0.0001 \
  --order-latencies-ns 0 1000000 \
  --half-spread-ticks 1 2 \
  --cancel-latency-ns 1000000 \
  --max-abs-inventory 0.01 \
  --output data/features/btcusdt-sensitivity.json
```

This example creates eight scenarios. Fees and order latency affect every
policy. `half-spread-ticks` affects the fixed-spread and inventory-skew policies;
the random and Avellaneda–Stoikov widths are controlled by their own recorded
parameters. The runner defaults to at most 100 scenarios to prevent accidental
combinatorial runs.

The grid is deterministic and source-linked. It is not a hyperparameter search
license: choosing the best test-period row would be data leakage. Select
parameters using train/validation periods, then evaluate the frozen choice once
on test data.

## Real-data smoke result

On the 2026-09-06 BTCUSDT smoke capture, using illustrative 1 ms order/cancel
latency, a 1 bp fee, 0.001 quote quantity, and the uncalibrated model defaults:

| Policy | Simulated fills | Net P&L (USDT) | Maximum absolute inventory (BTC) |
| --- | ---: | ---: | ---: |
| Fixed spread | 4 | -0.0310 | 0.00300 |
| Inventory skew | 4 | -0.0310 | 0.00300 |
| Seeded random | 1 | -0.0090 | 0.00100 |
| Avellaneda–Stoikov | 2 | -0.0116 | 0.00107 |

An eight-scenario grid also completed. For the fixed-spread policy, changing
latency from zero to 1 ms reduced simulated fills materially, while applying the
illustrative fee made net P&L more negative. This is expected sensitivity, not
evidence that latency improves a strategy.

The capture contains only 20 applied depth deltas and 182 trades. These figures
are software smoke observations, not statistically meaningful performance,
profitability, or model-calibration claims.

## Next gate before PPO

1. Collect longer independent sessions.
2. Estimate volatility and distance-dependent fill intensity on training data.
3. Run session-level chronological comparisons and confidence intervals.
4. Freeze simulator and baseline configurations.
5. Only then expose the same event state and execution rules through a new
   Gymnasium environment for PPO.

HMM remains an optional later feature and is not required for this gate.
