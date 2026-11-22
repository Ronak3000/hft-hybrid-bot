# ApexHFT — L2 direction baseline

Research question: do order-flow imbalance, microprice deviation, depth
imbalance, and spread predict the direction of the mid-price over the next
10, 50, or 100 emitted L2 feature rows? These are book updates, not trades
or fixed time intervals. Each report includes the mean actual receive-time
delay by session and horizon.

The target is the sign of the future mid minus the current mid (down, flat,
up). Inputs come only from the current feature row. Labels never cross
recordings or snapshot segments; the last horizon-sized tail of every segment
has no target. Whole sessions are assigned to chronological splits before
evaluation. Both scaling and logistic regression fit only the training split.
Buffered pre-snapshot updates warm up the book but do not produce feature
rows. Regenerate older feature CSVs that lack this availability filter.

## Run the first study

1. Capture or restore verified **Binance Spot L2** recordings. Use
   `python scripts/capture_binance_l2.py --symbol BTCUSDT --events 10000 --output data/captures/alpha/session-01.jsonl`
   and repeat under distinct filenames in non-overlapping time windows.
   Spread sessions across different periods; do not substitute candles.
2. Run `python scripts/build_l2_features.py data/captures/alpha/session-01.jsonl --output data/features/alpha/session-01.csv`
   for each recording. Keep each resulting manifest next to its CSV.
3. Install the optional dependency with `python -m pip install -r requirements-alpha.txt`.
   From the same activated environment, run this example once the splits and
   experiment settings are fixed (one session per split is only a smoke run):

   ```powershell
   python scripts/evaluate_lob_alpha.py --train data/features/alpha/session-01.csv --validation data/features/alpha/session-02.csv --test data/features/alpha/session-03.csv --output data/reports/lob-alpha-v1.json
   ```

Each split flag accepts multiple chronological files. Sessions must use the
same venue, symbol, and feature depth. The command verifies feature manifests,
rejects repeated captures or overlapping feature receive-time ranges, and
will not overwrite an existing report. It scores a train-majority control,
a zero-threshold microprice rule, and standardized logistic regression.
Reports include per-session and pooled accuracy, support, and confusion
matrices, plus macro-F1 averaged across all three labels (undefined class
scores count as zero).

For the temporal comparison, append `--lookback 8` to include an MLP on
eight consecutive feature rows. The existing controls are evaluated on the
same eligible rows as the MLP; train and test still use whole sessions.

Pooled scores describe prediction, not trade profitability. Adjacent targets
overlap; do not treat individual rows as independent for confidence intervals.
If you tune after reading a test report, use a later, untouched test split for
the revised experiment.

## Run the paired quoting replay

Once the horizon and widening distance are fixed, use a later, single-snapshot
capture and its verified feature CSV for each test run. The plain and widened
policies use identical Avellaneda–Stoikov coefficients, order size, fees,
latency, and inventory limits. A forecast moves only the exposed quote
outward (ask for up, bid for down). The model fits on training data only:
validation files establish the time boundary, and no test labels enter replay.
Use venue-appropriate tick size and fees; these are example settings:

```powershell
python scripts/evaluate_alpha_quotes.py --train data/features/alpha/session-01.csv --validation data/features/alpha/session-02.csv --test-capture data/captures/alpha/session-03.jsonl --test-features data/features/alpha/session-03.csv --horizon 10 --widen-ticks 1 --tick-size 0.01 --quantity 0.001 --maker-fee-rate 0.001 --order-latency-ns 1000000 --cancel-latency-ns 1000000 --inventory-limit 0.01 --output data/reports/alpha-quotes-v1.json
```

The report separates actual observed fill counts from missing markouts. A
negative signed mid-move P&L indicates adverse movement after the simulated
fill; it excludes the initial spread edge. Compare fill counts, inventory and
net P&L alongside markouts. A run without fills shows that the pipeline works,
not that either policy trades better. The candle PPO and C++ matching hot path
are unchanged.

Both test flags accept multiple paths in chronological order. List each
capture and its corresponding feature file in the same position. The report
includes per-session and mean net P&L differences versus the plain policy and
a fixed-width control. The control moves both quotes outward by the specified
ticks without predictions. It isolates a width-only reference, but does not
force the same quote activity or fill count as signal widening.

## Open the Research demos

Navigate to `/research` in the Next.js app. The two projects use separate,
linkable tabs; earlier PPO results are under **Earlier PPO pilot**.
**Order-book prediction** plays
the selected real recording or scores it immediately with **Run to end**.
Play, pause, step, or scrub; the realized direction only enters the confusion
matrix once the selected horizon has been observed. The browser scores
precomputed forecasts; it does not train a model or accept real orders.
**Queue-aware market making** displays the three strategies on identical test
recordings, including simulated fills, net P&L, and post-fill markouts.

The browser bundle contains derived features and report metrics, not raw
trade messages. To regenerate it, run `scripts/export_lob_research_demo.py`
with the same `--train`, `--validation`, and `--test` feature CSV lists as
the prediction evaluator, plus `--quote-report` and a fresh `--output` path.
Point the UI at the checked-in export after verifying it. The browser's
one-row logistic results are not the eight-row-window pilot table; the two
reports have different eligibility rules.
