# Phase 3: leakage-controlled HMM regimes

This phase adds an unsupervised Gaussian Hidden Markov Model research baseline.
It implements fitting and evaluation, but it does not claim that the states are
economically meaningful or profitable on real market data.

## Beginner mental model

An HMM assumes that the market moves through hidden states. We cannot observe a
state directly, but each state has a probability distribution over observable
features and a probability of transitioning to every other state.

In ApexHFT, the default observations are:

- spread in basis points;
- microprice deviation from the mid in basis points;
- multi-level depth imbalance;
- Level-1 order-flow imbalance.

Prices, timestamps, IDs, split names, and every `label_` column are excluded from
the model input. Raw price is intentionally omitted because its changing level
is generally less stationary than normalized microstructure features.

## Leakage controls

1. The scaler mean and standard deviation are fitted on `train` only.
2. HMM parameters are fitted on `train` only.
3. State count and random seed are selected by validation log likelihood per
   observation—not by returns or test performance.
4. Test likelihood and state summaries are computed only after selection.
5. Sequence lengths prevent transitions across L2 resynchronization segments.
6. Exported regime probabilities use the forward filter
   `P(state_t | observations_0..t)`. They do not use forward-backward smoothed
   probabilities, which would allow future observations to change past states.

The test suite directly changes future observations and verifies that all prior
filtered probabilities remain bit-for-bit unchanged. It also changes every
label and all test features, then verifies that the fitted scaler, model
parameters, and selected candidate remain unchanged.

## Model selection and stability

The baseline fits diagonal-covariance Gaussian HMMs over several state counts
and seeds. Each candidate records:

- convergence and iteration count;
- the tail of its EM likelihood history;
- whether the likelihood remained monotonic;
- minimum training state occupancy;
- train and validation likelihood per row;
- emitted warning count.

A run is rejected if it does not converge, its likelihood decreases materially,
or a state collapses below the configured occupancy threshold. The artifact also
reports validation-score mean, standard deviation, and range across valid seeds
for each state count.

Raw HMM state numbers are arbitrary. ApexHFT assigns deterministic `regime_id`
values by sorting training emission means. It deliberately does not name states
"bull", "bear", "toxic", or "safe" automatically.

## Install and run

The HMM dependency is optional so API and engine deployments do not carry the
extra scientific stack:

```bash
python -m pip install -r requirements-research.txt
```

Fit from the chronologically split dataset:

```bash
python scripts/fit_hmm_regimes.py \
  data/features/btcusdt-l5-h1000-split.csv \
  --states 2,3,4 \
  --seeds 7,19,41 \
  --iterations 250 \
  --artifact data/models/btcusdt-hmm.json \
  --predictions data/models/btcusdt-hmm-predictions.csv
```

The model artifact contains the frozen scaler, canonical transition and emission
parameters, all candidate diagnostics, per-partition likelihood and occupancy,
and descriptive state summaries. Its manifest hashes the artifact and links it
to the source dataset. The prediction CSV contains causal state probabilities.

The implementation pins `hmmlearn==0.3.3`. The project is in limited-maintenance
mode according to its package page, so the dependency and its behavior should be
reassessed periodically:
<https://pypi.org/project/hmmlearn/>

API reference:
<https://hmmlearn.readthedocs.io/en/stable/api.html#hmmlearn.hmm.GaussianHMM>

## What the tests prove

Synthetic two-regime data verifies:

- train-only standardization;
- validation-only selection;
- test and label isolation from fitting;
- causal forward probabilities;
- probability normalization;
- deterministic state numbering;
- artifact, prediction, and dataset provenance.

Synthetic recovery is a software-correctness test, not evidence of regimes in
BTCUSDT.

The current implementation loads each split into memory and assumes diagonal
Gaussian emissions. Large event-level datasets may require causal resampling,
chunked feature storage, or a different implementation. The Gaussian emission
and Markov assumptions must be diagnosed rather than treated as facts.

## What is still needed for a résumé claim

1. Collect multiple documented sessions or days, not a five-event smoke sample.
2. Pre-register feature set, horizons, state counts, seeds, and selection rule.
3. Report state occupancy, dwell time, transition stability, likelihood, and
   feature distributions across chronological validation and test periods.
4. Bootstrap confidence intervals by contiguous time blocks.
5. Test whether states add incremental predictive or execution value over simple
   spread/imbalance baselines after fees and latency.

Until those steps are complete, the truthful statement is that ApexHFT includes
a leakage-controlled HMM experimentation pipeline—not that it discovered
profitable market regimes.
