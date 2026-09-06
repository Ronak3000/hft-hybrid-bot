# ApexHFT

ApexHFT is an experimental market-microstructure research project. It combines a C++ order-book prototype, Python/Gymnasium strategy experiments, PPO training infrastructure, a FastAPI/Celery control plane, and a Next.js interface.

The project is under active validation. It is not an exchange, brokerage system, production trading platform, or demonstrated profitable strategy.

## Current capabilities

- A single-threaded, in-process C++ limit-order-book prototype with price-time matching.
- Intrusive FIFO queues at each price level.
- A preallocated order pool and fixed-size price-level storage.
- Hierarchical bitsets for locating the best bid and ask.
- Typed, allocation-free order outcomes covering executed, resting, and rejected quantity.
- CTest correctness coverage for validation, FIFO, price priority, partial fills, cancellation, pool exhaustion, reset, CSV replay, bit-tree boundaries, and deterministic differential testing.
- Python access to selected engine operations through Pybind11.
- A Gymnasium environment and Stable-Baselines3 PPO training path.
- Co-captured Binance Spot L2 snapshot/delta and individual public-trade
  streams, with depth-sequence validation, trade-ID diagnostics,
  hash-verified storage, and deterministic replay.
- Deterministic causal L2 feature generation for spread, microprice, depth
  imbalance, and Level-1 order-flow imbalance, with source-linked manifests.
- Timestamp-based forward-return labels that cannot cross sequence segments,
  plus chronological train/validation/test splits with boundary purging.
- A deterministic, exact-decimal paper-execution core with configurable order
  and cancel latency, conservative queue-ahead approximation, maker fees or
  rebates, inventory limits, and auditable fill records.
- A streaming verified-capture runner for fixed-spread and inventory-skew
  baselines, a seeded-random control, and a parameterized finite-horizon
  Avellaneda–Stoikov approximation, with source-linked deterministic JSON
  reports, fill rate, turnover, net/gross P&L, fee separation, inventory
  exposure, and post-fill markouts.
- A bounded sensitivity-grid runner for comparing fee, order-latency, and quote-
  width assumptions on identical capture bytes.
- FastAPI, Celery, Redis-compatible job handling, and optional Supabase model storage.
- A Next.js interface for training controls, an exchange-trade-driven paper simulation, and historical OHLCV visualization.

## Data and simulation status

There are currently three data paths:

1. `scripts/fetch_real_market_data.py` downloads up to roughly 400,000 Binance aggregate trades. Aggregate trades are executions, not Level-2 order-book snapshots or deltas.
2. `worker/utils/data_downloader.py` downloads one-minute OHLCV candles and converts them into synthetic add/execute messages. These generated events are not reconstructed exchange order flow or L2 data.
3. `scripts/capture_binance_l2.py` co-captures genuine Binance Spot REST depth snapshots, diff-depth WebSocket payloads, and individual public-trade messages. It preserves WebSocket arrival order, validates depth sequences, records trade-ID diagnostics and reconnect boundaries, writes files without overwriting them, and seals each capture with a metadata-and-SHA-256 manifest. The two WebSocket streams share a local connection but are not an exchange-atomic combined event. This is aggregated market-by-price L2 plus public executions, not market-by-order data or the strategy's fills.

The exchange-connected dashboard consumes Binance aggregate trade messages and applies local paper-fill logic. It does not submit, cancel, or reconcile orders with an exchange. No real funds are routed.

The historical page currently visualizes recent OHLCV candles only. It deliberately does not report strategy P&L, fills, win rate, or drawdown until a deterministic evaluation service replaces the former client-side mock results.

## Microbenchmark snapshot

An independent Windows/MSYS2 reproduction compiled the existing benchmark with `g++ -O3 -march=native` and observed approximately:

| Workload | Observed result |
| --- | ---: |
| Synthetic mixed engine actions | 11.9 million attempted actions/second |
| Synthetic mixed engine actions | 83.9 ns mean per attempted action |
| Hierarchical bit-tree loop | 87.2 million iterations/second |
| Hierarchical bit-tree loop | 11.5 ns mean per iteration |

These figures are single-threaded, in-process synthetic microbenchmark observations. They are not network, exchange round-trip, wire-to-wire, or production end-to-end latency measurements. The benchmark now reports fully accepted orders, rejected orders, successful crosses, and successful cancels separately, but it still lacks latency percentiles, CPU affinity, and complete hardware metadata. Treat the numbers as preliminary engineering measurements, not performance guarantees.

## Known limitations

- The L2 pipeline currently supports Binance Spot only and has not yet produced a published research dataset window.
- The OHLCV-derived worker still generates execute events with unrelated order IDs, so those events normally cannot identify a resting order even though replay now supports partial execution correctly.
- The C++ matching engine intentionally does not model participant accounts.
  The separate paper simulator tests cash, inventory, fees, and turnover, but it
  is not an exchange clearing or reconciliation system.
- The historical RL environment has not yet demonstrated meaningful fills or PPO learning.
- Exact queue position is unobservable from market-by-price L2. A documented
  conservative queue-ahead approximation is implemented, but displayed
  cancellations currently receive no queue credit.
- The new execution core is not yet connected to the Gymnasium environment or
  PPO. All four initial baselines are implemented, but the Avellaneda–Stoikov
  volatility and arrival-decay parameters have not been fitted on a substantial
  training dataset.
- No checked-in experiment demonstrates PPO outperforming fixed-spread, inventory-aware, Avellaneda-Stoikov, random, or other baselines.
- No claim of cross-asset transfer, profitability, drawdown reduction, or adverse-selection reduction has been validated.
- The `Order` type is not declared `alignas(64)`; only the surrounding slab allocation requests 64-byte alignment.
- The current Docker Compose file does not include the frontend or Redis and requires external configuration for the full service flow.

See the source and limitations before interpreting any UI output. The immediate project priority is correctness, deterministic replay, and reproducible evaluation.

See [the Phase 2 guide](docs/phase2-l2-data.md) for the L2 sequencing model,
capture command, integrity verification, and current research limitations.
The follow-on [causal feature guide](docs/phase2-l2-features.md) defines the
formulas, leakage boundary, reproducibility metadata, and feature-build command.
[The labels and splits guide](docs/phase2-labels-splits.md) explains timestamp
horizons, gap isolation, chronological evaluation, and purging at boundaries.
[The real-time market-data guide](docs/phase3-realtime-market-data.md) explains
the co-captured trade stream, its integrity checks, and what it can and cannot
support in the upcoming execution simulator.
[The execution-simulator guide](docs/phase4-queue-simulator.md) defines the
latency, queue, fill, fee, and accounting assumptions used by the new core.
[The capture-baseline guide](docs/phase5-capture-baselines.md) documents the
warmup boundary, policy definitions, reproducible report command, and the first
real-data smoke result.
[The Phase 6 guide](docs/phase6-as-random-sensitivity.md) defines the seeded
random control, Avellaneda–Stoikov units, and bounded sensitivity grid.

## Repository layout

```text
engine/backend_cpp/       C++ order-book prototype and Pybind11 module
engine/rl_trading/        Gymnasium environment
worker/                   Celery training task and data downloader
api/                      FastAPI control plane
web/                      Next.js interface
scripts/                  Data, training, evaluation, and model utilities
```

## Local development

### Build the Python extension

Requirements include a C++ compiler, CMake, Python development headers, and Pybind11's CMake package.

```bash
cmake -S engine/backend_cpp -B engine/backend_cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build engine/backend_cpp/build --config Release
```

### Run the C++ correctness suite

This configuration skips the Python extension so engine tests only require a C++20 compiler and CMake:

```bash
cmake -S engine/backend_cpp -B engine/backend_cpp/build-tests \
  -DCMAKE_BUILD_TYPE=Release \
  -DAPEXHFT_BUILD_PYTHON=OFF \
  -DBUILD_TESTING=ON
cmake --build engine/backend_cpp/build-tests --config Release
ctest --test-dir engine/backend_cpp/build-tests --output-on-failure -C Release
```

The `engine_correctness_tests` executable includes both focused scenarios and a seeded 5,000-operation comparison against a slower reference order book.

Sanitizer instrumentation is available with `-DAPEXHFT_ENABLE_SANITIZERS=ON` when the selected GCC or Clang installation includes AddressSanitizer and UndefinedBehaviorSanitizer runtimes.

### Run the synthetic benchmark

```bash
cmake -S engine/backend_cpp -B engine/backend_cpp/build-bench \
  -DCMAKE_BUILD_TYPE=Release \
  -DAPEXHFT_BUILD_PYTHON=OFF \
  -DAPEXHFT_BUILD_BENCHMARKS=ON
cmake --build engine/backend_cpp/build-bench --config Release
```

Run `engine_benchmark` from the generated build directory. Results remain synthetic and in-process.

### Start the API

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Start the worker

Configure Redis/Celery and optional Supabase environment variables first, then run:

```bash
celery -A worker.tasks.rl_training worker --loglevel=info
```

### Start the web interface

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:3000`.

## Research roadmap

The intended progression is:

1. Matching correctness and invariant tests (baseline implemented; property/fuzz coverage will continue to expand).
2. Sequence-valid L2/trade co-capture, causal features, timestamp labels, and purged chronological splits (initial pipeline implemented; substantial multi-session collection remains).
3. Queue-aware paper execution approximations with latency, fees, auditable accounting, capture replay, and initial P&L attribution (implemented; sensitivity studies remain).
4. Fixed-spread, inventory-skew, seeded-random, and parameterized Avellaneda–Stoikov baselines plus initial sensitivity tooling (implemented; substantial chronological evaluation remains).
5. Improve PPO only after the simulator and deterministic baselines are credible; treat Hidden Markov Model regime probabilities as an optional research extension, not a prerequisite.
6. Chronological, multi-seed out-of-sample evaluation with confidence intervals.
7. Reproducible benchmark reports and an offline demo.

## Responsible-use note

ApexHFT is research software. It should not be used to route real funds or make investment decisions without substantial additional engineering, validation, operational controls, and regulatory review.
