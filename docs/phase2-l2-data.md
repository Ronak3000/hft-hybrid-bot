# Phase 2: sequence-valid Level-2 data

This phase added a separate Binance Spot Level-2 capture and replay path. The
collector now also stores the individual public-trade stream described in the
[Phase 3 guide](phase3-realtime-market-data.md). It does not convert candles or
trades into invented orders, and it does not change the C++ matching-engine hot
path.

## Beginner mental model

A snapshot is a photograph of every visible price level returned by the venue.
A delta says which price levels changed afterward. The update IDs are the page
numbers: if a page is missing, continuing would produce a plausible-looking but
wrong book. ApexHFT therefore marks the book unsynchronized and obtains a fresh
snapshot after a gap.

For a synchronized book whose latest ID is `n`:

- a delta ending at or before `n` is stale and is ignored;
- a delta whose range contains `n + 1` can be applied;
- a delta starting after `n + 1` proves that data is missing and forces resync.

This implements Binance's documented snapshot-plus-diff-depth procedure. A
Binance REST depth snapshot is capped, so this is an aggregated view of the
visible price levels returned by that snapshot—not market-by-order data and not
guaranteed knowledge of levels outside the snapshot limit.

Official protocol reference:
<https://developers.binance.com/zh-CN/docs/products/spot/testnet/web-socket-streams#how-to-manage-a-local-order-book-correctly>

## What was added

- Frozen snapshot, delta, public-trade, and price-level schemas.
- Exact decimal parsing; exchange prices and quantities never pass through
  binary floating point.
- Venue/symbol checks, range checks, duplicate-level rejection, and crossed-book
  rejection.
- Stale, applied, gap, and needs-snapshot outcomes.
- Gap-triggered reconnection and snapshot resynchronization in the live capture.
- Exclusive-create JSONL files so an earlier dataset cannot be overwritten.
- A manifest containing collection metadata, byte count, record count, schema
  version, and SHA-256.
- Deterministic replay with a canonical final-state digest.
- Tests for sequencing, deletion, atomic rejection, tampering, immutability, and
  repeatable replay.

The JSONL contains venue payloads plus the local receive timestamp. A completed
file is append-only and overwrite-protected by the writer. Its manifest detects
accidental changes relative to the recorded hash. Do not edit either file;
derive features into a different directory. This is an integrity mechanism, not
a digital signature against a malicious party who can replace both files.

## Install and capture

Install the repository requirements in a virtual environment. Then, from the
repository root:

```bash
python scripts/capture_binance_l2.py \
  --symbol BTCUSDT \
  --events 1000 \
  --depth-limit 1000 \
  --output data/captures/btcusdt-example.jsonl
```

The output path must not already exist. Network interruptions and update gaps
are recorded, followed by a new connection and snapshot. The command stops if
the configured reconnection limit is exceeded and still seals the partial file
with a manifest.

## Verify and replay

```bash
python scripts/replay_l2.py data/captures/btcusdt-example.jsonl
```

The replay first verifies the manifest. It then reports sequencing counts, the
final best bid/ask, synchronization status, and a state digest. Replaying the
same capture must always produce the same digest.

## Run tests

```bash
python -m unittest tests/test_l2_market_data.py -v
```

These tests use small checked-in fixtures and do not need network access.

## Reproduction smoke check

On 2026-09-06, the original depth-only collector completed a local BTCUSDT smoke
run containing one snapshot, 10 applied deltas, three correctly ignored stale
buffered deltas, zero gaps, and a synchronized final book. The Phase 3 guide
records the later combined-stream smoke check. Raw smoke files are intentionally
ignored by Git; these checks establish that the network path works, but they are
not a published dataset or a research result.

## Performance boundary

The L2 validator is deliberately separate from `MatchingEngine::process_order`.
Applying a delta uses an in-place update plus a small undo log, avoiding a full
copy of the book while preserving atomic failure behavior. This is a correctness
pipeline, not yet a latency benchmark. The existing C++ benchmark remains the
guard for accidental matching-engine regressions.

## Still required before research claims

1. Capture a documented dataset window and publish only its manifest and
   collection metadata if the raw file is too large or redistribution is not
   permitted.
2. Add clock-quality metadata and measure local receive delay distributions.
3. Convert validated L2 states into causal features such as spread, depth,
   microprice, and multi-level order-flow imbalance.
4. Build the queue-aware fill simulator before evaluating strategies.
5. Fit an HMM only on training-period features; freeze preprocessing and model
   parameters before evaluating chronological validation/test periods.
