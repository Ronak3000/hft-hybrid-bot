# Working real-data replay

## Run the demo

The repository includes static, capture-derived playback assets. No API keys,
Redis, Supabase, Python service, Celery worker, or trained model is needed to
view them. From the repository root:

```powershell
npm --prefix web ci
npm --prefix web run dev
```

Open `http://localhost:3000/replay`. For a production build, use
`npm --prefix web run build`, then `npm --prefix web run start`.

1. Select a real recording and the saved PPO policy or a rule-based control.
2. Press Play. The default 30x playback advances the recorded clock faster
   than wall time; 1x, 10x, and 60x are also available.
3. Pause or scrub the timeline. The order book, hypothetical quotes, queue-ahead
   estimates, fill ledger, marked-to-market P&L, fees, and inventory follow the cursor.
4. Switch between market and P&L charts. The whole recording is shown faintly
   for navigation; the highlighted portion ends at the current replay position.
5. Compare the full-recording summaries, or download the complete sampled
   replay JSON including all simulated fills, configuration, and source hash.

The first frame is before strategy action, so zero fills and no open quotes are
expected until playback advances. Only the most recent 20 fills at the cursor
are rendered, but all simulated fills are in the downloaded artifact.

## What is real, and what is modeled

The order-book prices and depth come from real Binance Spot BTCUSDT captures.
Order placement, queue position, fills, fees, and portfolio accounting are
simulated by the existing `QueueReplayEnv` / `QueueAwareSimulator` path.

The bundled examples use the first and last **training** captures by planned
ordinal, including every snapshot-delimited segment. All ten training sessions
were validated before export. No validation or test capture bytes are used.
The demonstration is not held-out evaluation, an exchange order feed, or
evidence of profitability. The bundled PPO model is a single-seed, 16,384-step
training demonstration. It produces zero fills on both displayed recordings;
the narrow fixed/inventory policies lose money. No-quote and widest-grid fixed
are zero-fill controls. Zero P&L from inactivity does not establish an edge.

The fixed settings are 0.001 BTC quotes, 0.01 BTC inventory cap, 1 ms order and
cancel latency, a modeled 0.1% maker fee, and two-tick maximum inventory skew.
Narrow controls use a five-tick half width; the widest fixed control uses
10,000 ticks. PPO selects quote/stay out, half width, and skew from its frozen
action space. The fee is an experiment assumption, not a current
exchange quote. These policies demonstrate the system; they were not selected
for attractive P&L. Market impact and exact market-by-order queue position are
not observable in the replay.

Bundled policy decisions have a target minimum interval of one second, while every
intervening captured event is processed. Display frames have a target minimum
interval of one second, plus the initial and final state. Actual timestamps
remain irregular. End-of-capture invalidates hypothetical open orders.

Each replay is content-addressed and its SHA-256 is checked in the browser
against the catalog before it is displayed. This detects asset/catalog
inconsistency; it is not an independent attestation of the catalog. Raw capture
hashes link back to local source data, but raw captures are not bundled and
cannot be independently reconstructed from the sampled frames alone.

## Regenerate from local captures

With the Python environment activated and all training sessions valid:

```powershell
python scripts/export_replay_demo.py --plan data/studies/btcusdt-ppo-v2-activity-v1.json
```

That command exports the original baseline-only demo (250 ms decisions).
To reproduce the bundled PPO-plus-controls version, first train the model
using [the declared configuration](phase16-ppo-replay.md), then run:

```powershell
python scripts/export_replay_demo.py --plan data/studies/btcusdt-ppo-v2-activity-v1.json --ppo-metadata engine/saved_models/btcusdt-v2-demo-seed-7-16384.json
```

PPO export needs PyTorch and Stable-Baselines3 locally. Viewing the exported
site does not: predictions are precomputed and model weights stay local.

This writes content-addressed runs and atomically updates
`web/public/replays/catalog.json`. It refuses to overwrite unrelated producer
catalogs or conflicting replay bytes. It does not modify raw captures, open
held-out capture files, or make network requests. Unreferenced old export assets
are left in place, not deleted automatically.

The four focused replay tests check decimal account identity, fill visibility,
deterministic output, zero-activity accounting, reconnect-segment handling,
causal PPO action execution, artifact tampering, and shared frozen costs.
Browser verification covers playback, seeking, both recordings, policy changes,
JSON download, SHA-256 failure handling, and narrow-screen layout. No C++
benchmark changes are involved.
