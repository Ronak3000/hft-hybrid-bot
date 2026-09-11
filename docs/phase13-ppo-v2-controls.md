# Phase 13: PPO v2 activity controls

PPO v1 produced a useful negative result: it traded enough that fees dominated
its P&L, beat the fixed-spread and random controls, but did not beat the
Avellaneda–Stoikov or inventory-skew policies. PPO v2 must address activity and
experimental design without tuning on the consumed final-test sessions.

## Why “more training” is not the first fix

For mid-price `P`, fee rate `f`, tick size `t`, and symmetric half-width `h`
ticks, a rough round-trip comparison before adverse selection is:

```text
captured spread per unit ≈ 2 * h * t
round-trip fees per unit ≈ 2 * f * P
fee-only break-even half-width ≈ f * P / t ticks
```

For example, at a 60,000 price, 0.1% per-fill fee, and 0.01 tick, the fee-only
half-width is about 6,000 ticks. A 1–5 tick action range cannot cover that cost
through spread capture. This example explains the scale mismatch; it is not a
claim about the current exchange fee schedule or a profitable quote width.

The correct response is not to hide fees or reward the agent for trading. A
policy must be allowed to abstain, and zero P&L from no activity is a baseline
that every fee-inclusive strategy should beat.

## Changes in PPO v2

### Configurable decision interval

`QueueReplayEnv` now accepts `decision_interval_ns`. The default is zero, which
preserves PPO v1 behavior and compatibility with existing model sidecars. With
a positive interval:

- the current quote target remains active;
- every intervening L2 delta and public trade is still processed causally;
- fills, queue consumption, latency, fees, and book state continue to update;
- the agent receives its next observation on the first applied depth delta at
  or after the interval.

This reduces forced policy decisions and potential cancel/requote churn without
downsampling or discarding market events.

Training records the interval in model metadata. Held-out PPO and baseline
evaluation read the same value, so all policies retain identical decision
opportunities.

### Mandatory no-quote baseline

The paired evaluator now includes `no_quote`, which cancels both sides and holds
zero inventory. Its expected fee-inclusive P&L is zero. A strategy that loses
to this baseline has not justified taking market risk, even if it beats an
active random policy.

The paired-report schema is version 2 because the baseline set changed. Old
reports remain valid version-1 historical artifacts.

## Beginner-safe PPO v2 study

Do not retrain and evaluate on `test-001` or `test-002`; they were opened for
the PPO v1 final result. Keep them as historical evidence only.

1. Collect a new, later chronological study with substantially more independent
   sessions. The flagship target remains 10 training, 5 validation, and 10 test
   sessions rather than one long file split into artificial samples.
2. Record the actual fee tier being modeled. Treat zero-fee or rebate settings
   as named sensitivity scenarios, never as the primary real-fee result unless
   they match an attainable venue/account tier.
3. Before validation, freeze a small activity-control grid such as decision
   intervals `{100 ms, 250 ms, 1000 ms}` and entropy coefficients
   `{0, 0.001}`. Do not search dozens of combinations.
4. Train at least three predetermined seeds for each candidate using training
   captures only.
5. Choose one configuration on validation using a predeclared rule that first
   requires beating `no_quote`, then compares fee-inclusive P&L, adverse
   selection, turnover, inventory, fill rate, and rejection rate.
6. Freeze the selected configuration and evaluate once on the new test split.

An example v2 training argument is:

```bash
--decision-interval-ns 250000000 --entropy-coefficient 0.001
```

This is an experiment candidate, not a recommended or validated setting.

## Next model changes

Only after the activity-control ablation should the observation vector change.
The next candidates are causal rolling order-flow imbalance, signed trade
imbalance, short-horizon realized volatility, and quote age. Add them one group
at a time and compare against the same non-HMM PPO. An HMM remains optional and
should enter only as a later held-out regime-feature ablation.
