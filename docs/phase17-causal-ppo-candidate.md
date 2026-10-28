# Causal state and one-sided PPO candidate

## Declared before training

The previous demonstration predominantly abstains. At the unchanged modeled
0.1% maker fee, each roughly 80-USDT fill costs about 0.08 USDT. Narrow-spread
turnover can be structurally unattractive; activity is not itself an objective.
This candidate improves the policy's information and available decisions,
without promising a profitable result or forcing trades.

- Optional observation schema 2: legacy 14 features plus 12 bounded causal
  features for basis-point spread/microprice/returns, 5s/30s price momentum,
  time-aware volatility, aggressive trade-volume imbalance and log volume,
  five-level depth imbalance, existing quote distances, and elapsed time.
- Optional action schema 3: off, both, buy-only, sell-only, with factorized
  width and skew. The same queue simulator, fees, latency, and inventory caps
  execute all actions. A one-sided sell quote can reduce a long position
  without simultaneously requesting another buy, and vice versa.
- History resets at each capture/sequence segment. Only already processed
  trades and book events contribute to the current observation.
- Legacy schemas remain the defaults, preserving saved model behavior.

One seed-7 candidate will be trained for 65,536 steps using the ten validated
training captures only. It retains the earlier execution settings, width grid
[1, 100, 1000, 8000, 10000], skew ±2, 1-second decisions, 0.01 reward scale,
0.01 inventory penalty, 2x64 Tanh network, and learning rate 0.0003.
Gamma 0.999 and GAE 0.99 extend credit assignment; entropy coefficient 0.01
maintains more exploration. Rollout 2048, batch 64, epochs 10, CPU thread 1.
This is a bundled candidate with a larger budget, not an isolated causal
ablation or a hyperparameter optimum. No profitability/learning claim follows
from training alone.

Evaluate the old and new deterministic policies across **all ten training
captures**, including each reconnect segment, with identical execution costs.
Report P&L, fills, fees, turnover, order rejections and action frequencies.
Do not inspect validation/test captures or replace a better reference with a
worse model merely because it trades more. Do not change fees or reward fills.

The C++ engine and financial accounting core are unchanged. Feature arithmetic
is approximate floating-point input only; cash/fees remain exact decimal.

## Reproduce locally

With the repository root as the working directory and an environment containing
Gymnasium, PyTorch and Stable-Baselines3:

```powershell
python scripts/train_queue_ppo.py --plan data/studies/btcusdt-ppo-v2-activity-v1.json --tick-size 0.01 --quantity 0.001 --max-abs-inventory 0.01 --maker-fee-rate 0.001 --order-latency-ns 1000000 --cancel-latency-ns 1000000 --action-schema-version 3 --observation-schema-version 2 --max-half-spread-ticks 10000 --half-spread-tick-choices 1 100 1000 8000 10000 --max-absolute-skew-ticks 2 --decision-interval-ns 1000000000 --reward-scale 0.01 --inventory-penalty-per-second 0.01 --entropy-coefficient 0.01 --gamma 0.999 --gae-lambda 0.99 --total-timesteps 65536 --seed 7 --device cpu --require-fee-coverage --output engine/saved_models/btcusdt-causal-sides-seed-7-65536.zip

python scripts/compare_training_ppo.py --plan data/studies/btcusdt-ppo-v2-activity-v1.json --models engine/saved_models/btcusdt-v2-demo-seed-7-16384.json engine/saved_models/btcusdt-causal-sides-seed-7-65536.json --output data/reports/causal-sides-training-comparison-v1.json

python scripts/export_replay_demo.py --plan data/studies/btcusdt-ppo-v2-activity-v1.json --ppo-metadata engine/saved_models/btcusdt-causal-sides-seed-7-65536.json --output web/public/replays/causal-candidate
```

Each command refuses conflicting output instead of replacing a prior model or
report. The experimental replay has its own catalog and assets; the reference
model remains unchanged. Open `/replay?variant=causal` for the candidate, or
`/replay` for the reference. Both are labeled training demonstrations.

## Completed result: activity improved, net performance did not

Both deterministic policies were replayed across all ten training captures,
with unchanged costs and no held-out files opened:

| Model | Training steps | Simulated fills | Gross marked-to-market P&L | Fees | Net P&L |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reference | 16,384 | 0 | 0 | 0 | 0 |
| Causal + one-sided candidate | 65,536 | 95 | +1.179215 | 6.52981764 | -5.35060264 |

Amounts are USDT, aggregated across independent reset accounts. Gross means net
plus modeled fees, including final inventory marked at mid; this is not all
realized profit. Nine candidate sessions lost money and one was positive.
No statement about generalization, statistically established alpha, or net
outperformance is supported. The reference remains the default.

Candidate action requests: off 5,780; both 1,561; buy-only 540; sell-only 1,624.
These are decisions, not fills. The policy does use the new side choices.

The first/last training replay selection remains unchanged. Candidate train-001
has 1 fill and +0.01325395 net; train-010 has 3 fills and -0.40022499 net.
The browser displays the all-ten negative result prominently alongside these
examples so the positive first recording is not presented as the study result.

- Model SHA-256: `c3e487e563fb2fc314f3ca9ebd29e6ae38779398cc71221fe182e16090875e5c`
- Sidecar SHA-256: `671118a2f34b02981ca5f746fcfd8811dc8df7658b47e38298fccc58206dcb44`
- Full report: `data/reports/causal-sides-training-comparison-v1.json`
- Report SHA-256: `66acc2500af976123f8858f79ce0c4fa1c30cac968d1debfc44f0bb6479627ca`

This removes two representation/control limitations and establishes a measured
active candidate, but does not solve the fee hurdle. The next step should be
training-only fee/markout attribution and a matched-budget ablation, not a
claim that more fills prove a better trader. Additional causal features add
optional Python feature-computation cost; the legacy observation path and C++
matching hot path remain unchanged. No engine performance claim was retested.
