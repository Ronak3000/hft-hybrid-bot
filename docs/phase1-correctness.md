# Phase 1: Matching-engine correctness

This document explains the first ApexHFT correctness milestone without assuming prior exchange knowledge.

## The mental model

A limit order says: buy or sell a quantity, but never at a worse price than the specified limit.

Orders that cannot trade immediately wait in the book. Matching follows two rules:

1. **Price priority:** the best price trades first.
2. **Time priority:** at the same price, the oldest order trades first (FIFO).

For every submitted quantity, the engine must account for all units:

```text
requested quantity = executed quantity + resting quantity + rejected quantity
```

That equality is a basic invariant: a rule that must remain true after every operation.

## What changed

- Order submission now returns a typed, fixed-size `ProcessResult` instead of a success string.
- Invalid sides, prices, quantities, IDs, and duplicate active IDs are rejected before book mutation.
- Pool exhaustion is explicit, including the quantity that could not rest.
- Historical execution events reduce a resting order by their quantity instead of acting like full cancellation.
- Reset returns every slot to the preallocated pool.
- Aggregate-trade paper signals no longer overwrite actual order-book price levels.
- Price-level volume uses 64 bits to reduce overflow risk.
- Slab storage constructs and destroys C++ objects correctly instead of treating raw zeroed bytes as live objects.
- CSV replay accepts an optional header, retains the first headerless row, rejects malformed rows, and requires nondecreasing timestamps.

## Avoiding hot-path deoptimization

The ordinary `process_order` path does not allocate memory for trade reports. It returns a small summary value. A separate templated `process_order_with_sink` path lets tests or research code receive each fill through a caller-owned callback. With the no-op sink used by normal processing, the compiler can inline and remove fill-reporting work.

A local before/after guardrail used five alternating runs of binaries compiled with the same command and pre-instrumentation benchmark source:

| Version | Median mixed throughput | Median mean loop time |
| --- | ---: | ---: |
| Before correctness refactor | 21.64M attempted actions/s | 46.22 ns/action |
| After correctness refactor | 21.93M attempted actions/s | 45.61 ns/action |

The roughly 1.3% difference is within normal desktop benchmark noise. It provides no evidence of a hot-path regression, but it is not a production performance claim. The newer benchmark performs extra outcome accounting and therefore represents a different workload.

## What the tests prove

The suite checks:

- invalid inputs do not mutate the book;
- duplicate IDs do not orphan the original order;
- better prices execute before worse prices;
- older orders execute first at the same price;
- partial fills preserve the remaining quantity;
- canceling a middle order keeps queue links valid;
- exhausted pool capacity produces an explicit rejection and recovers after cancellation;
- reset restores book and pool state;
- an aggressive order cannot leave the book crossed;
- headerless CSV replay retains its first event;
- malformed history is rejected;
- bit-tree boundary prices work;
- 5,000 seeded random actions agree with a slower reference order book after every step.

## How to run it

From the repository root:

```bash
cmake -S engine/backend_cpp -B engine/backend_cpp/build-tests \
  -DCMAKE_BUILD_TYPE=Release \
  -DAPEXHFT_BUILD_PYTHON=OFF \
  -DBUILD_TESTING=ON
cmake --build engine/backend_cpp/build-tests --config Release
ctest --test-dir engine/backend_cpp/build-tests --output-on-failure -C Release
```

On MinGW, the test and benchmark executables statically link the runtime. This avoids accidentally loading Git for Windows' incompatible `libstdc++-6.dll` from `PATH`, a failure discovered while building this test suite.

## Continuous integration

GitHub Actions runs the Release correctness suite on Linux and Windows. A separate Linux job runs the same suite with AddressSanitizer and UndefinedBehaviorSanitizer, keeping correctness instrumentation separate from performance builds.

## Remaining Phase 1 work

- Add longer property tests and fuzz malformed replay input.
- Add a deterministic book-state checksum for larger replay tests.
- Move participant cash and inventory conservation tests into the queue-aware simulator milestone.
