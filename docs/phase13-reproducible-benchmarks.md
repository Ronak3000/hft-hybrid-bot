# Phase 13: reproducible engine benchmarks

Phase 13 separates throughput measurement from latency-distribution sampling.
This matters because reading a clock for every operation changes the workload
being measured. Neither executable measures networking, exchange round trips,
kernel-bypass I/O, or production wire-to-wire latency.

## Two deliberately separate measurements

`engine_benchmark` retains the existing long, minimally instrumented synthetic
throughput loops. It reports attempted operations, successful outcomes, total
elapsed time, mean loop time, and checksums.

`engine_latency_benchmark` uses a different `OrderBook` instance, performs a
warmup, and times batches of mixed actions. It reports p50, p99, and p99.9 of
the **amortized nanoseconds per action within each batch**. These percentiles
are not individual-order latency percentiles; batching reduces clock overhead
while still exposing run-to-run scheduling noise and long-tail batches.

Keeping this sampler in a separate executable prevents its clock reads, sample
vector, sorting, and JSON formatting from changing the throughput benchmark.

## Build and run

Use a Release build and record the exact configure/build commands:

```bash
cmake -S engine/backend_cpp -B engine/backend_cpp/build-bench \
  -DCMAKE_BUILD_TYPE=Release \
  -DAPEXHFT_BUILD_PYTHON=OFF \
  -DAPEXHFT_BUILD_BENCHMARKS=ON
cmake --build engine/backend_cpp/build-bench --config Release
```

Run the original throughput executable first. Then run the latency executable:

```bash
engine_latency_benchmark \
  --actions 1000000 \
  --warmup-actions 20000 \
  --batch-size 256 \
  --seed 42
```

For the recommended multi-process report, use the wrapper. It performs one
discarded process warmup, runs five recorded processes, verifies that workload
outcomes and checksums are identical, captures host and executable provenance,
and refuses to overwrite an existing report:

```bash
python scripts/run_engine_benchmark_suite.py \
  --binary engine/backend_cpp/build-bench/engine_latency_benchmark \
  --runs 5 \
  --cpu 2 \
  --output data/benchmarks/engine-latency-host-date.json
```

Choose a CPU available to the process. Omit `--cpu` when affinity is unsupported
and the report will explicitly record that no pinning was requested.

The latency executable writes one JSON object containing:

- compiler name/version, build mode, C++ standard, architecture, detected
  instruction-set level, and logical hardware-thread count;
- the RNG seed, warmup size, action count, batch size, and sample count;
- mean, p50, p99, and p99.9 amortized batch latency;
- attempted/successful crosses and cancels, accepted/rejected orders, final
  active orders, and an anti-optimization checksum.

Redirect the JSON to a new result file whose name includes the date, host, and
compiler. Do not overwrite or hand-edit raw results. Also retain the compiler
command line, CPU model, power plan, foreground/background load, and whether
CPU affinity was applied. The executable cannot discover all of those details
portably, so they remain required experiment metadata rather than guessed
fields.

## Reporting rules

Run at least five independent process invocations after a warmup invocation.
The wrapper records every run and summarizes median/minimum/maximum; do not
publish only the fastest run. Compare commits only on the same machine,
compiler, flags, affinity, power/thermal conditions, parameters, and benchmark
source.

Use claims such as “single-threaded, in-process synthetic mixed-action
throughput” and “amortized batch-latency distribution.” Never call either
number end-to-end latency or exchange latency.
