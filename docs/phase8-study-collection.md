# Phase 8: predeclared multi-session data collection

Phase 8 turns one-off connectivity captures into an auditable research dataset.
The split assignment and quality rules are sealed before data is collected.
Every completed capture is then checked for integrity, identity, chronology,
duplicate content, sequence quality, and minimum event counts.

This phase does not change the C++ matching engine and does not submit orders to
an exchange.

## Beginner workflow

### 1. Start with a pilot plan

Run this from the repository root:

```bash
python scripts/create_study_plan.py \
  --study-name btcusdt-pilot-v1 \
  --symbol BTCUSDT \
  --capture-directory data/captures/btcusdt-pilot-v1 \
  --training-sessions 2 \
  --validation-sessions 1 \
  --test-sessions 2 \
  --events-per-session 10000 \
  --min-trades-per-session 1000 \
  --max-depth-gaps-per-session 0 \
  --max-trade-gaps-per-session 0 \
  --max-disconnects-per-session 2 \
  --output data/studies/btcusdt-pilot-v1.json
```

The command creates the plan and a SHA-256 manifest using exclusive file
creation. Do not edit them after collection begins. Commit these two small files
so the repository records that the split was chosen before policy results were
seen. Raw files under `data/captures/` remain ignored by Git.

The pilot is a software and operations rehearsal, not the final statistical
study. A later flagship plan should contain many more independent sessions and
a larger event target, chosen after measuring pilot collection quality—not
after selecting profitable-looking results.

### 2. Capture exactly the next session

```bash
python scripts/capture_study_session.py \
  --plan data/studies/btcusdt-pilot-v1.json \
  --session-id train-001
```

The wrapper reads symbol, depth, event target, reconnect limit, output path, and
quality thresholds from the sealed plan. It refuses an unknown session, an
existing output, or a session whose earlier planned sessions are missing or
invalid. Repeat with `train-002`, `validation-001`, `test-001`, and `test-002`.

Capture sessions at meaningfully different times instead of running them back
to back as one continuous sample. The exact spacing is a study-design choice;
record it before the flagship collection.

### 3. Audit progress

Use a new audit filename each time because reports are also exclusive-create:

```bash
python scripts/audit_study.py \
  --plan data/studies/btcusdt-pilot-v1.json \
  --allow-incomplete \
  --output data/features/btcusdt-pilot-audit-01.json
```

`incomplete` is expected while planned sessions remain. `fail` means at least
one existing capture was rejected. A failed capture is evidence; do not delete
or replace it silently. Preserve it, explain the cause, and create a newly
versioned plan if collection must restart.

The final audit passes only when every planned session is valid. It records:

- the plan hash and every capture hash;
- start/end local receive times and duration;
- WebSocket receive-timestamp regressions, which must remain zero (the
  documented REST-snapshot/buffer serialization boundary is excluded);
- applied and stale depth deltas;
- accepted, duplicate, and out-of-order trades;
- depth gaps, trade-ID gaps, and disconnects;
- final synchronization state;
- valid capture filenames grouped by train, validation, and test.

Sessions must be strictly non-overlapping in their planned order. Identical
capture bytes under different filenames are rejected.

## Moving from pilot to the research study

After the pilot:

1. Review capture duration, trade counts, disconnect frequency, disk use, and
   whether the chosen thresholds are realistic.
2. Write a new flagship plan, for example 10 training, 5 validation, and 10 test
   sessions with 100,000 applied depth deltas each.
3. Spread sessions across different times and days using a schedule decided in
   advance.
4. Complete and pass the audit before fitting or evaluating policies.
5. Calibrate Avellaneda–Stoikov only with the audit's training files.
6. Use validation sessions for configuration decisions.
7. Evaluate frozen policies once on test sessions.

Session counts and event targets are design examples, not a guarantee of
statistical power. The eventual report must include the actual session count,
coverage period, missing/rejected sessions, parameter choices, and confidence
intervals.

## PPO gate

Do not train the replacement PPO environment on test sessions. First make the
same queue simulator and observation builder consume training sessions, tune on
validation, then compare multiple frozen PPO seeds against all deterministic
baselines on the untouched test set. HMM regime features remain an optional
ablation after that baseline is credible.
