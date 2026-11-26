# Real-data training, historical testing and live paper inference

The intended product workflow is restored:

1. Select BTCUSDT, ETHUSDT or SOLUSDT and a historical UTC period in Model
   Training. The server downloads real public Binance.US minute candles.
2. Validate every selected chunk, then train PPO and save weights plus configuration.
3. Choose either a later historical test period or the current live public feed.
   Both use the saved model without further learning. The historical and live
   desks render market candles, paper P&L and fill markers. No orders are routed.

## Local setup

Install requirements in the Python environment used to start the API. Start
`python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers`.
Use one API process only; the local job coordinator is not a distributed queue.
Start the web app with `npm run dev` from `web`. The UI defaults to port 8000
for the API, configurable with `NEXT_PUBLIC_API_URL`.

Routes: `/train`, `/backtest`, `/dashboard`.
For a short demo, use **Recent demo hour**, train, then follow **Test on
history** or **Test live**. Wait at least two minutes for a live candle update.
Jobs run in the background; the page polls real status, not fabricated progress.
Cancel stops downloads/evaluation cooperatively and terminates the training child.
An interrupted PPO optimization restarts, not resumes from an optimizer
checkpoint. The optional L2 downloader reuses verified completed chunks.

## Historical periods and access

Training defaults to **free Binance.US 1-minute candles for the selected UTC range**.
The three workspace tabs are Model Training, Historical View and Live Trade.
BTCUSDT, ETHUSDT and SOLUSDT use separate model/data identities. No Tardis key
is used in this candle workflow. The downloader requests bounded minute pages;
valid missing minutes in historical data split the PPO run into flat-start
episodes, with gap intervals recorded in UTC milliseconds. No candles or rewards
are interpolated across a gap. Live inference uses frozen weights and stops if
its required feed continuity is lost. The C++ matching engine is separate and
does not execute these candle-policy decisions. The separate
long/flat policy observes a completed candle and models a position change at the
next close (0.001 units of the selected asset, no fees or slippage). Price movement before that paper fill
is credited only to existing inventory. Candle models are not queue-aware; saved
weights are dispatched to the same candle environment on historical or live data.
Live mode waits for newly completed exchange minutes; a short session may see none.

Choose previous 1, 3 or 6 completed UTC calendar months, a custom number of
completed days, or exact UTC start/end. End is exclusive. All selected minutes
are requested; there is no downsampling into a small undocumented sample.

## Optional BTCUSDT L2 path (API, not the default training form)

The API can train on an approved study-plan training recording or download the
free BTCUSDT raw replay sample for 2024-01-01 00:00–00:01 UTC. A corrupt or
explicitly selected missing recording fails closed. Custom historical periods
never silently switch to the free sample.

The provider is [Tardis raw Binance Spot archive](https://docs.tardis.dev/historical-data-details/binance).
Its `depthSnapshot` channel contains REST-sourced exchange snapshots, despite the
provider's `generated:true` wrapper. We reconstruct book state from real snapshots
and sequence-checked deltas; we do not create liquidity or arrivals from candles.
See [access and replay API](https://docs.tardis.dev/api/http-api-reference).
First-of-month data can be available without a key; other dates require a
server-side `TARDIS_API_KEY`. There is no guaranteed free arbitrary-date L2 archive.
The API's estimate endpoint counts archive requests and reports missing access
before training.

Downloads split into at most ten-minute chunks, carrying verified book/trade-ID
state forward. Initial daily snapshots require warm-up from UTC midnight.
Every requested minute must contain records; gaps, reconnects inside a chunk,
out-of-order records, missing snapshots and access failures abort the job.
This conservative implementation does not bridge a missing market segment.
Completed chunks remain reusable; it is not yet a general recovery service for
months containing exchange outages.

Captures and manifests live in `data/workbench/archive` (or under
`APEX_WORKSPACE_DATA`). SHA-256 hashing is bounded-memory. Capture and manifest
publication is atomic per chunk. Dataset manifests seal the complete selected
interval and ordered capture hashes. Missing or corrupt chunks prevent training.
The selected GiB budget counts complete dataset bytes, including cached chunks;
one in-progress chunk may temporarily exceed it before the job stops. Disk checks
also stop downloads if less than 512 MiB remains. No automatic old-data deletion.

Six months can mean over 250,000 minute requests, substantial disk space and
millions of PPO decisions. Estimates are request/step counts, not invented speed
or storage forecasts. A small smoke test does not validate six-month operational scale.

## User controls

PPO: total steps, rollout size, batch size, epochs, learning rate, gamma, GAE
lambda, policy/value clipping, entropy/value coefficients, gradient norm,
target KL, advantage normalization, hidden layers/width, activation,
orthogonal initialization, seed, CPU threads and device.

L2 API simulation: quote quantity, initial cash, inventory cap, fee rate, order/cancel
latency, decision interval, reward scale, inventory penalty, spread choices,
maximum skew and optional entry cost guard. The venue profile remains BTCUSDT
with tick size 0.01 and versioned 26-feature/factorized-action schemas; these are
not arbitrary user-overridable identities.

Invalid settings fail validation, including non-finite numbers, incompatible
rollout/batch sizes and excessive quote quantity. Total steps must be a rollout
multiple and enough to traverse the chosen dataset. A completed artifact requires
every selected capture to have reached its end at least once. All settings are
stored beside the model; test/live inference uses that configuration.

Zero fees is the default experimental setting requested by the owner. It is
displayed explicitly and does not support a fee-inclusive profitability claim.
Hyperparameter flexibility is not evidence that PPO has improved.

## Interpretation and limits

L2 archive training and historical evaluation use independent chunk episodes, resetting
inventory and cash at each chunk. The sum of net P&Ls is an episode aggregate,
not a continuous multi-month trading portfolio. The simulation assumes queue
ahead and latencies; actual private queue positions and counterfactual exchange
fills cannot be recovered from public L2. Bootstrap fixtures remain tests only.

Historical test data must be later than all training data. A saved model is
loaded only from trusted operator-owned directories after its weight hash and
metadata are checked. No model upload or arbitrary file path is exposed.
Existing study-plan weights remain listed when their metadata/plan hash matches.

L2 live inference uses the same observation/action/accounting logic via a bounded
forward-only record queue, records a real-data journal, and halts on a missing
sequence, stale consumer or disconnect. Sessions are bounded to 10–300 seconds.
It does not automatically reconnect and continue a potentially invalid account.

## Hosting

Set `NEXT_PUBLIC_API_URL` on Vercel to the Render API URL and rebuild the frontend.
On Render set `APEX_OPERATOR_TOKEN`, `CORS_ORIGINS` to the exact frontend origin,
`APEX_WORKSPACE_DATA` to a directory on persistent writable storage, and optional
`TARDIS_API_KEY` for archive access. Enter the operator token in the UI; never put
secrets in `NEXT_PUBLIC_*` variables. Without a token, only loopback requests are
allowed; Render requires a token regardless of proxy address.

These jobs no longer depend on an unavailable Supabase/Redis/Celery service.
Old Celery jobs still fail rather than invoking the deleted synthetic worker.
The local single-process job runner is not a production distributed scheduler:
server restart interrupts a run, and interrupted work is reported explicitly.
Keep the server alive for long downloads and training; do not run multiple API
processes against the same data directory.

Docker honors `PORT` and copies training scripts. Docker Compose binds the API
to loopback, requires an operator token and mounts the local workbench directory.
Free ephemeral hosting does not reliably retain models across redeploys.

## Local verification

With the Python requirements and `httpx` installed, run:

```sh
python -m scripts.smoke_candle_workbench --symbol BTCUSDT
```

Repeat for ETHUSDT and SOLUSDT. The script uses a temporary model/data directory,
trains on a small recent window, verifies checkpoint registration, tests a
disjoint window and waits for newly closed live candles. It checks plumbing,
not profitability; a frozen policy may choose not to trade.
