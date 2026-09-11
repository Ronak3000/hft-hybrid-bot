# Phase 12: BTCUSDT PPO pilot result

The first sealed multi-seed PPO pilot was run on 2026-09-11. This is a software
and methodology result, not evidence of profitability or statistical proof.

## Frozen setup

- Real Binance Spot BTCUSDT market-by-price L2 deltas and public trades.
- Two training sessions, one validation session, and two final-test sessions;
  each session contains 10,000 applied L2 deltas.
- PPO seeds 7, 19, and 43, each trained for 102,400 steps.
- Queue-aware replay, 1 ms order/cancel latency, 0.1% maker fee, 0.001 BTC
  quote size, and 0.01 BTC absolute inventory limit.
- Seed outputs were averaged inside each capture session before uncertainty was
  calculated across sessions.
- The final test was opened once only after the experiment bytes and evaluation
  rule were frozen.

The local final report is
`data/features/btcusdt-pilot-v1-ppo-final-test.json` (19,954 bytes, SHA-256
`4d6b4c11bc5b9b98e9c3c85b94ecffff49dead2588403a15eff79f43fa11204b`).
Raw captures and trained models are intentionally not committed to Git.

## Final-test result

There are only two test sessions. The intervals below are deterministic
session-level percentile-bootstrap intervals, but with two sessions they should
be read as a range-like pilot diagnostic, not a reliable confidence interval.

| Policy | Mean net P&L | 95% session bootstrap interval |
| --- | ---: | ---: |
| PPO seed mean | -45.58 | [-60.56, -30.60] |
| Avellaneda–Stoikov | -34.47 | [-47.00, -21.94] |
| Fixed spread | -51.18 | [-67.88, -34.49] |
| Inventory skew | -3.40 | [-6.13, -0.67] |
| Seeded random | -48.72 | [-63.62, -33.83] |

Paired session differences for PPO minus each baseline were:

| Comparison | Mean difference | 95% session bootstrap interval |
| --- | ---: | ---: |
| PPO minus fixed spread | +5.61 | [+3.89, +7.32] |
| PPO minus seeded random | +3.15 | [+3.06, +3.23] |
| PPO minus Avellaneda–Stoikov | -11.11 | [-13.56, -8.66] |
| PPO minus inventory skew | -42.17 | [-54.42, -29.93] |

All evaluated policies lost money after fees. PPO beat the fixed and random
controls on these two sessions, but it did not beat the stronger deterministic
baselines. The inventory-skew policy traded much less (21 and 57 fills across
the two sessions), so its smaller loss is not evidence of a scalable edge.

## What can be claimed

The defensible result is that ApexHFT now supports integrity-checked,
chronological, multi-seed PPO evaluation against four policies on identical
queue-replay episodes with explicit fees and latency. It is not defensible to
claim PPO outperformance, profitability, or generalization.

Future PPO changes may use the old training and validation periods for
diagnosis, but must use a newly predeclared, later test window for any new final
claim. The consumed two-session test split must not become tuning data and then
be presented again as unseen.
