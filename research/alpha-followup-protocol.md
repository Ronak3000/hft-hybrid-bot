# Multi-day L2 follow-up protocol

The existing 22 November pilot is for development and UI demonstration.
Do not reuse those two test recordings for a new performance claim.

## Collection

- BTCUSDT on Binance Spot, co-captured diff depth and public trades.
- Target four or more distinct UTC dates and three separated windows on
  each date. Use earlier dates for training, the following date for
  validation, and later untouched dates for testing. Add more test dates
  before attempting session-level uncertainty estimates.
- Use a new capture name every time. Record planned UTC windows and actual
  capture hashes, and log all missed or rejected recordings. For the
  main comparison, use single-snapshot sessions with no depth gaps,
  trade-ID gaps, reconnects, duplicates, or out-of-order trades. Never fill
  missing market data. Keep raw recordings and manifests unchanged.
- Start with 10,000 applied depth updates per study session. A shorter
  follow-up collection is useful as a development check, not a replacement
  for the declared study sample.

## Freeze before testing

Use training rows only for model/scaler fitting. Use validation alone to
select the horizon and quote widening. Freeze the training and validation
hashes, prediction model and quote settings before inspecting any test
outcomes. Record the assumed fee, order and cancel latencies, tick size,
order size, inventory cap, and simulator version.

On each fresh test session, compare plain Avellaneda–Stoikov, fixed
symmetric widening without predictions, and one-sided signal widening.
Report per-session prediction class support and macro-F1, plus paired net
P&L, fills, inventory, and 100 ms / 1 s signed mid-move P&L. On post-fill
metrics, report observed counts; absent markouts are not zero. A symmetric
control does not have the same activity as the signal arm; a subsequent
activity-matched control can isolate that distinction.

See the [commands and browser export guide](../docs/lob-alpha.md).
