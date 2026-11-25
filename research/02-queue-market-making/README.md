# Project 2 — Queue-aware market making

**Question:** Does a frozen direction signal improve simulated quoting versus
the same Avellaneda–Stoikov policy without the signal?

[Replay instructions](../../docs/lob-alpha.md#run-the-paired-quoting-replay) ·
[Paired replay command](../../scripts/evaluate_alpha_quotes.py) ·
[Quote adjustment code](../../engine/research/alpha_quotes.py)

[Read the five-session pilot results](../pilot-2026-11-22.md#project-2--paired-quotes).

The baseline sets a reservation price and spread. The experimental policy
widens only the side exposed to the forecast direction, without changing the
order size. It uses the logistic model from Project 1, not the optional MLP.
Predictions become available only when their exact depth event arrives.

Pass multiple later captures and matching feature files to get per-session
paired results. Both arms use the same fee, latency, and inventory settings
and the same market-by-price replay. Compare net P&L, fills, inventory, and
signed post-fill mid-price movement together. Estimated fills and queue
positions are not exchange fills or exact order priority.

## Arrival-model development

`scripts/evaluate_trade_hawkes.py` now fits a fixed-decay, two-sided Hawkes
model on the observed arrival times of aggressive buys and sells. It uses
verified uninterrupted public trade captures, not generated events or
inferred L3 submissions. Chronological validation/test reports compare
the fitted model with independent constant-rate Poisson controls. The local
receive clock includes feed timing and batching, so this is not a matching
engine clock. The spectral radius is reported; an unstable fit is not a
usable stationary arrival model.

```powershell
python -m pip install -r requirements-alpha.txt
python scripts/evaluate_trade_hawkes.py --train data/captures/train-01.jsonl --validation data/captures/validation-01.jsonl --test data/captures/test-01.jsonl --output data/features/trade-hawkes-development.json
```

## PPO and SAC on the L2 queue

The offline comparison feeds frozen, two-sided Hawkes intensities to both
agents. Each rate uses strictly earlier trade receive timestamps. The script
rejects an unstable Hawkes fit or a fit from a different training capture list.
PPO and SAC use the same three normalized controls: bid offset from best bid,
ask offset from best ask, and shared capped order size. Controls map to fixed
tick and size grids; zero size leaves the market. Resizing or withdrawing
quotes still goes through the simulator's latency-aware cancellation rules.
The candle model is not involved.

```powershell
python -m pip install stable-baselines3==2.7.1
python scripts/evaluate_arrival_rl.py --train data/captures/train-01.jsonl --validation data/captures/validation-01.jsonl --test data/captures/test-01.jsonl --hawkes-report data/features/trade-hawkes-development.json --steps 512 --output data/features/arrival-rl-development.json --weights-dir data/features/arrival-rl-development-models
```

Both learned agents and the two rule-based baselines run on identical replay
sessions with a common fee, latency, and inventory cap. Agent reward is
fee-inclusive change in marked-to-market value minus an inventory penalty;
the report gives actual simulated P&L before that reward-only penalty.
Post-fill markouts use the first observed depth update at or after each
horizon, with counts for fills whose markouts are observable. Open inventory
is marked to mid at capture end, not assumed liquidated at that price.

Use `--seeds 7 19 43` for a repeated development comparison. Each seed has
its own validation-size control: take the learned policy's mean requested
size per quoted side on validation, round to the closest allowed nonzero
size (ties down), then freeze that size for the inventory-skew test.
If the agent never quotes on validation, no matched control is reported.
This controls quoted size, not time in market, fill counts, or inventory.
Seeds evaluated on the same test captures are not independent market samples.

## Fill probabilities

The separate probe evaluator samples independent, unamended hypothetical
quotes from the observed L2 book. It predicts **any simulated fill** by a
fixed deadline, including partial fills, with activation latency and initial
queue from the existing simulator. Inputs are known at quote submission:
side, distance from touch, spread, displayed queue, size, and touch imbalance.
Quotes rejected at activation are non-fills. Probes without a complete
observation window are excluded, even if a fill already occurred. Multiple
probes can see the same public trades, so their outcomes are not independent.

```powershell
python scripts/evaluate_fill_probability.py --train data/captures/train-01.jsonl --validation data/captures/validation-01.jsonl --test data/captures/test-01.jsonl --horizon-ms 1000 --output data/features/fill-probability-development.json
```

Compare the training fill-rate control, logistic probabilities, and
probabilities recalibrated on validation. The report gives Brier score,
log-loss, reliability bins, censoring, and held-out session counts.
These are fill probabilities **under the simulator's assumptions**, not
observed exchange fill probabilities for our orders. Pass `--fill-report`
to the PPO/SAC runner to compare identical observation layouts with the
probabilities visible or replaced with zeros. Profile inputs describe a
fresh quote at the specified offsets and maximum quote size, not the
remaining lifetime of an existing order. The runner checks matching
training/validation captures, tick size, size grid, and activation latency.

On the reused five-session development pilot, 96 of 2,136 eligible test
probes filled. Validation recalibration reduced pooled Brier score from
0.04355 (training fill rate) to 0.04290. With 512 steps per learner and
seeds 7, 19, and 43, both PPO and SAC lost more than their validation-size
inventory-skew controls on both test sessions for every seed.
Neither result establishes generalization. A frozen study still needs
longer untouched sessions on different dates. The Research tab now shows
the arrival, fill calibration, and fill-feature comparison, with the earlier
deterministic replay results below them.

The three-seed, 512-step fill-feature ablation on the same development
recordings produced identical per-session seed-mean fills and P&L with
and without the probability inputs. Both learners also remained below
their size-matched controls. This says the feature did not change the
observed outcomes in this short run; it does not show the feature is
generally ineffective.
