# Phase 7: training-only calibration and session-level evaluation

This phase adds a leakage-resistant bridge between the deterministic baselines
and future PPO work. It fits the two data-dependent Avellaneda–Stoikov inputs on
explicit training captures, freezes those values, and compares policies on
different chronological capture sessions.

It does not establish profitability or prove that any policy is superior. The
current real-data smoke capture is too short, and there are not yet enough
independent sessions for a meaningful confidence interval.

## 1. Collect separate sessions

Create several captures at different times using the Phase 3 capture command.
Decide which sessions are training data before looking at policy results. Keep
later sessions for evaluation. Do not split individual messages randomly.

Each capture must retain its generated manifest. Calibration and evaluation
verify the manifest and record the capture SHA-256, so the exact input bytes can
be audited later.

## 2. Fit only on training captures

Example:

```bash
python scripts/calibrate_as.py \
  --training-captures \
    data/captures/train-day-1.jsonl \
    data/captures/train-day-2.jsonl \
  --distances 0.01 0.02 0.05 0.10 \
  --output data/features/btcusdt-as-calibration.json
```

Distances use quote-currency price units. For BTCUSDT, `0.01` means 0.01 USDT.
Choose distances on the instrument's tick grid and record the choice before
evaluating policies.

The volatility estimate is:

```text
sigma = sqrt(sum(mid-price change^2) / sum(local receive-time change in seconds))
```

The arrival proxy counts public aggressive trades whose price reaches each
distance from the then-current mid. It divides counts by twice the synchronized
exposure time to produce a per-side rate, then fits:

```text
lambda(distance) = A * exp(-k * distance)
```

using ordinary least squares on the logarithm of positive-count bins. The
calibrator refuses zero price variation, insufficient positive bins, or a fit
whose intensity does not decrease with distance. It records the fit's
R-squared as a diagnostic; a fitted coefficient does not imply a good model.

This is deliberately labelled a **public aggressive-trade reach proxy**. L2
market-by-price data cannot reveal the exact queue position or hypothetical fill
intensity of an order that was never sent. The fitted `k` is useful as a frozen
model input, but it is not a measured private fill probability.

## 3. Evaluate later sessions with frozen parameters

Example:

```bash
python scripts/evaluate_sessions.py \
  --calibration data/features/btcusdt-as-calibration.json \
  --sessions \
    data/captures/test-day-1.jsonl \
    data/captures/test-day-2.jsonl \
    data/captures/test-day-3.jsonl \
  --tick-size 0.01 \
  --quantity 0.001 \
  --maker-fee-rate 0.0001 \
  --order-latency-ns 1000000 \
  --cancel-latency-ns 1000000 \
  --max-abs-inventory 0.01 \
  --output data/features/btcusdt-session-evaluation.json
```

The evaluator refuses an evaluation capture whose content hash appeared in the
calibration inputs. It also refuses duplicate evaluation content. Every policy
runs on every accepted session with the same simulator assumptions.

The report contains per-policy mean net P&L, fill count, and turnover. It also
reports paired session-level net-P&L differences between each policy and the
fixed-spread baseline. The deterministic percentile interval resamples complete
sessions with replacement. Messages inside one capture are serially dependent,
so treating them as independent observations would produce misleadingly narrow
intervals. The report retains the full evaluation configuration, capture
metadata and hashes, and the calibration-file hash.

## Current software smoke check

The existing 2026-09-06 BTCUSDT combined-stream capture successfully exercised
the calibrator at distances 0.01, 0.02, 0.05, and 0.10 USDT. It contained only
1.94 seconds of synchronized exposure and 20 mid-price-change observations.
The resulting numbers are deliberately not published as fitted market
parameters. The evaluator correctly refuses to reuse this training capture as
an out-of-sample session.

Two sessions are the minimum needed by the tool, not an adequate research
sample. Use many sessions spanning different times and conditions, and report
the session count beside every interval. If an interval crosses zero, the study
does not show a reliable difference under the tested configuration.

## What to do next

1. Collect a predeclared multi-day training/validation/test dataset.
2. Calibrate on training only and choose simulator/policy settings on validation.
3. Freeze the configuration and evaluate once on untouched test sessions.
4. Review fill rate, inventory, turnover, fees, markouts, and paired P&L—not P&L
   alone.
5. Connect this same observation and execution path to a replacement Gymnasium
   environment.
6. Train PPO across several seeds and compare it with all four frozen baselines
   using the same session-level protocol.

An HMM can remain a later ablation for regime-conditioned features. It is not
required for a credible PPO experiment.
