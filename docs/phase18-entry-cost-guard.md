# Entry-cost overlay: same-checkpoint training comparison

## Declared before the comparison

Keep the phase-17 PPO weights, capture set, fees, latency, quantities and risk
limits fixed. Compare all ten training captures with the optional entry guard
disabled versus enabled at zero extra basis-point buffer. No validation/test
files are opened. This isolates a deterministic rule overlay on a fixed policy,
not a newly learned network or an independent performance claim.

For a requested buy, current-mid edge after the entry fee is
`mid - price * (1 + fee_rate)` per base unit. For a sell it is
`price * (1 - fee_rate) - mid`. Veto exposure additions when this is below
`mid * buffer_bps / 10000`. Zero buffer is not zero fees.

Inventory reductions may pass the veto, with requested quantity capped at
the existing absolute position. Reconciliation cancels oversized existing
orders before replacement, respecting cancellation latency. Pending orders
may still fill before cancellation; the rule cannot guarantee a reduce-only
fill or nonnegative P&L under latency.

The guard is optional and disabled by default. It is applied both at decisions
and when reconciling after public trades, using only the currently known book
and position. It does not delete fills retrospectively, alter fees or reset
inventory. It does not cover exit fees, guarantee future mid, forecast alpha,
or solve adverse selection. Existing accounting and C++ are unchanged.

Optional research-only fill diagnostics record the current mid at each fill,
signed spread capture and fees. Total P&L decomposes as spread capture plus
inventory revaluation minus fees. Inventory revaluation includes adverse and
favorable moves together; it is not a causal estimate of adverse selection.

```powershell
python scripts/compare_fee_guard.py --plan data/studies/btcusdt-ppo-v2-activity-v1.json --model engine/saved_models/btcusdt-causal-sides-seed-7-65536.json --buffer-bps 0 --output data/reports/entry-guard-training-v1.json
```

If this improves net P&L only by not trading, report that as loss avoidance,
not trading skill. Keep the reference and unguarded replay available.

## Completed comparison

| Same PPO checkpoint | Fills | Spread capture | Inventory revaluation | Fees | Net P&L |
| --- | ---: | ---: | ---: | ---: | ---: |
| Unguarded | 95 | +0.226095 | +0.953120 | 6.52981764 | -5.35060264 |
| Entry-cost guard, zero extra buffer | 0 | 0 | 0 | 0 | 0 |

Amounts are USDT across ten independent training accounts. All 95 unguarded
fills had contemporaneous spread capture below their own entry fee. This does
not mean each fill ultimately lost individually: subsequent price movement
can compensate. It does show how small initial execution edge was relative to
the unchanged modeled fee. Inventory revaluation is descriptive, not an alpha
or adverse-selection estimate. No forward price was fed to the guard or PPO.

The guard improved this in-sample net result by abstaining. It did not produce
profitable trades or beat the no-quote reference. There is no basis to promote
it as a trading breakthrough or resume profitability claim.

- Checkpoint SHA-256: `c3e487e563fb2fc314f3ca9ebd29e6ae38779398cc71221fe182e16090875e5c`
- Report: `data/reports/entry-guard-training-v1.json`
- Report SHA-256: `28f2ef7c39ec8166591a8efe97c061b86be362883b2a4e9c39bdad5705361bc5`

Inspect the separately labeled replay at `/replay?variant=fee`. Export command:

```powershell
python scripts/export_replay_demo.py --plan data/studies/btcusdt-ppo-v2-activity-v1.json --ppo-metadata engine/saved_models/btcusdt-causal-sides-seed-7-65536.json --entry-fee-buffer-bps 0 --output web/public/replays/fee-guard
```

The downloaded replay records the explicit overlay, unchanged model hash and
unchanged 0.1% per-fill fee. All displayed controls use the same guard. The
reference and unguarded candidate remain accessible; the default is unchanged.
Future training can opt in using `--entry-fee-buffer-bps`, which is stored in
the sidecar and restored by evaluation/replay. The network in this comparison
was not retrained under that rule.

Next meaningful research is a train-only, chronological test of whether
features predict moves large enough to cover both entry/exit costs and risk.
More fills or more training steps cannot establish that signal by themselves.
