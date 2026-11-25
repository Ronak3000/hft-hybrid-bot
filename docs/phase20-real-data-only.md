# Real market inputs only: removal record

Historical record, superseded by [phase 21](phase21-real-data-workbench.md).
Removing the historical training/test features was an overly broad interpretation
of the request. Those features are now restored on genuine data, with no return
of the fabricated market generators. The availability descriptions below record
the intermediate revision, not the current API.

At the user's request, remove fabricated market-data paths rather than relabeling
them. Existing raw captures, immutable reports, trained models, and real-data
replay assets are preserved. Deleted source files remain recoverable in Git.

## Removed

- OHLCV-to-add/execute-event generator and its stochastic side selection.
- Aggregate-trade-to-engine-order converter: observed executions must not be
  silently represented as reconstructed order arrivals.
- Legacy `TradingEnv`, its Gym registration, old training/evaluation entrypoints,
  test-CSV fallback, fixed initial prices, and trade-tick-derived fill physics.
- C++ `inject_live_tick`, invented bid/ask depth, default ticker/depth fields,
  and its obsolete tick-update microbenchmark block. The matching hot path is
  unchanged. `advance_tick` returns NaN when no two-sided midpoint is available;
  it no longer invents a price. Previously compiled extensions need rebuilding.
- Historical simulation/preview UI and API; old live dashboard and training forms.
- Prefilled trading stores and the obsolete live chart.
- Fabricated landing-page book: replaced by a hash-checked recorded Binance
  snapshot. If unavailable, display unavailable, never an illustration/fallback.
- Synthetic throughput claim on the landing page. Archived engineering numbers
  remain explicitly historical/synthetic, never relabeled as real-feed latency.

## Fail-closed behavior

Old training start/status, engine control, and historical simulation endpoints
return HTTP 410. Live status reports UNAVAILABLE without any price/account
values. The legacy WebSocket sends only an unavailable explanation and closes.
Stale queued legacy training tasks raise an explicit error before data access,
training, model upload, or registration. No replacement Celery job is implied.

The default Compose profile and start script do not launch the retired worker.
Any optional compatibility worker uses environment configuration, not embedded
credentials; credentials previously committed must still be rotated externally.
Missing model-registry configuration produces HTTP 503 rather than stopping
the API from exposing honest health/availability responses.

## What remains

`capture_binance_l2.py` captures genuine Binance L2 snapshots/deltas and public
trades. Verified capture plans feed `train_queue_ppo.py`, feature extraction,
sealed evaluation, and the recorded-data replay. Missing or invalid captures
are errors, not a trigger for generated market history.

Paper orders, queues, and fills remain explicitly simulated execution on real
inputs. Actual historical strategy fills cannot be observed for hypothetical
orders. No real orders are sent to Binance. The saved 26-feature model is NOT
connected to live Binance L2 yet; removal does not claim that adapter is complete.

Deterministic unit-test fixtures, reference-book randomized correctness checks,
statistical bootstrap resampling, and randomized strategy controls remain
isolated from market-data acquisition. They do not manufacture a feed for the
bot. Synthetic engineering microbenchmarks are opt-in (CMake default OFF), not
trading data and not evidence of real-data throughput or live exchange latency.

These are repository changes, not a confirmed Render deployment. The deployed
service continues running its existing revision until updated. Render's existing
model-registry DNS failure requires separate environment/log inspection.
