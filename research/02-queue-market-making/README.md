# Project 2 — Queue-aware market making

**Question:** Does a frozen direction signal improve simulated quoting versus
the same Avellaneda–Stoikov policy without the signal?

[Replay instructions](../../docs/lob-alpha.md#run-the-paired-quoting-replay) ·
[Paired replay command](../../scripts/evaluate_alpha_quotes.py) ·
[Quote adjustment code](../../engine/research/alpha_quotes.py)

[Read the five-session pilot results](../pilot-2026-11-22.md#project-2--paired-quotes).

The baseline sets a reservation price and spread. The experimental policy
widens only the side exposed to the forecast direction, without changing the
order size. It uses the logistic model from Project 1, not the optional MLP.
Predictions become available only when their exact depth event arrives.

Pass multiple later captures and matching feature files to get per-session
paired results. Both arms use the same fee, latency, and inventory settings
and the same market-by-price replay. Compare net P&L, fills, inventory, and
signed post-fill mid-price movement together. Estimated fills and queue
positions are not exchange fills or exact order priority.
