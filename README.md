# ApexHFT

ApexHFT is an experimental market-microstructure research project. It combines a C++ order-book prototype, Python/Gymnasium strategy experiments, PPO training infrastructure, a FastAPI/Celery control plane, and a Next.js interface.

The project is under active validation. It is not an exchange, brokerage system, production trading platform, or demonstrated profitable strategy.

## Current capabilities

- A single-threaded, in-process C++ limit-order-book prototype with price-time matching.
- Intrusive FIFO queues at each price level.
- A preallocated order pool and fixed-size price-level storage.
- Hierarchical bitsets for locating the best bid and ask.
- Python access to selected engine operations through Pybind11.
- A Gymnasium environment and Stable-Baselines3 PPO training path.
- FastAPI, Celery, Redis-compatible job handling, and optional Supabase model storage.
- A Next.js interface for training controls, an exchange-trade-driven paper simulation, and historical OHLCV visualization.

## Data and simulation status

There are currently two data paths:

1. `scripts/fetch_real_market_data.py` downloads up to roughly 400,000 Binance aggregate trades. Aggregate trades are executions, not Level-2 order-book snapshots or deltas.
2. `worker/utils/data_downloader.py` downloads one-minute OHLCV candles and converts them into synthetic add/execute messages. These generated events are not reconstructed exchange order flow or L2 data.

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

These figures are single-threaded, in-process synthetic microbenchmark observations. They are not network, exchange round-trip, wire-to-wire, or production end-to-end latency measurements. The current benchmark counts attempted operations rather than verified successful operations and does not report latency percentiles, CPU affinity, or complete hardware metadata. Treat the numbers as preliminary engineering measurements, not performance guarantees.

## Known limitations

- There is no genuine L2 snapshot-and-delta ingestion pipeline yet.
- Historical execute messages are not modeled with correct partial-fill semantics.
- Matching-engine correctness tests and CTest targets have not yet been added.
- Duplicate IDs, invalid price ranges, pool exhaustion, and reset behavior need stricter handling.
- The historical RL environment has not yet demonstrated meaningful fills or PPO learning.
- Queue position, configurable latency, adverse selection, and complete fee accounting are not yet modeled.
- No checked-in experiment demonstrates PPO outperforming fixed-spread, inventory-aware, Avellaneda-Stoikov, random, or other baselines.
- No claim of cross-asset transfer, profitability, drawdown reduction, or adverse-selection reduction has been validated.
- The `Order` type is not declared `alignas(64)`; only the surrounding slab allocation requests 64-byte alignment.
- The current Docker Compose file does not include the frontend or Redis and requires external configuration for the full service flow.

See the source and limitations before interpreting any UI output. The immediate project priority is correctness, deterministic replay, and reproducible evaluation.

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

The current CMake file builds the `hft_engine` Python extension only. A first-class benchmark and CTest target are planned but do not exist yet.

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

1. Matching correctness and invariant tests.
2. Sequence-valid L2 snapshot/delta capture and deterministic replay.
3. Queue-aware paper execution with latency, fees, and auditable accounting.
4. Fixed-spread, inventory heuristic, Avellaneda-Stoikov, random, and PPO baselines.
5. Hidden Markov Model regime probabilities using causal order-flow features.
6. Chronological, multi-seed out-of-sample evaluation with confidence intervals.
7. Reproducible benchmark reports and an offline demo.

## Responsible-use note

ApexHFT is research software. It should not be used to route real funds or make investment decisions without substantial additional engineering, validation, operational controls, and regulatory review.
