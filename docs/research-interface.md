# Research interface

The landing page and `/research` are static Next.js pages with a shared dark
workspace theme, responsive navigation, keyboard focus indicators, and a skip
link. They can be viewed without Redis, the Python API, a model, or an exchange
connection. There are no new runtime packages, polling loops, or chart libraries.

## What is shown

- The landing-page order book is illustrative and explicitly labeled as not
  live market data. Its prices and quantities are layout examples.
- `/research` summarizes the documented 2026-09-11 BTCUSDT pilot, not a new run.
- The five policy means are rounded values from
  `docs/phase12-ppo-pilot-results.md`; the UI data lives in
  `web/src/lib/research.ts` and links back to those source notes.
- P&L is mean fee-inclusive USDT per test session. PPO is first averaged across
  the three seeds within each session. All displayed means are negative.
- The two-session sample, exact-queue uncertainty, non-live nature, legacy UI
  boundary, and absence of a profitability claim are visible in the page.
- The v2 study card reads the validated training count from the bundled replay
  catalog and links to the working player. The validation/test counts remain
  collection targets, not live progress. Counts describe the export snapshot.
- Raw captures, model weights, and the full evaluation JSON are not bundled.
  The displayed report hash is recorded provenance, not an in-browser hash
  verification of an available raw report.

The separate `/replay` page is now an interactive player for exported real
training captures. Its controls operate entirely in the browser after loading
the static assets; it needs no Python API or Redis. An initial page load still
requires the web server; no service worker or downloaded-site offline cache is
implemented. See [the replay walkthrough](phase15-working-replay.md).
The player now includes a single-seed PPO v2 training demonstration and four
controls, using precomputed causal model outputs. It shows the actual zero-fill
result, model identity, and last sampled decision. This is separate from the
older three-seed held-out pilot summarized on `/research`.

## Review locally

From `web`, install the lockfile dependencies with `npm ci` if needed, run
`npm run build`, then `npm run start`. Visit `/replay` for the working demo,
or `/research` for the historical pilot notes.

Review both a desktop viewport and a narrow mobile viewport. Check that:

1. Navigation opens Real-data replay, Research overview, Legacy simulator, Historical data, and
   Model training, and the current item is identified.
2. The research page renders with the API stopped and makes no API/WebSocket
   requests. Its external source links point to the repository documentation.
3. Values match the pilot notes, including negative signs and the two-session
   limitation. No control advertises simulated returns as live trading results.
4. There is no horizontal page overflow; all icon-only navigation links have
   accessible names, focus is visible, and the report-hash disclosure works.

The shared typography variables now refer to the actual loaded font variables,
instead of a recursive monospace variable and an unset sans-serif variable.
The C++ engine and its benchmark workloads are unchanged by this UI work.
