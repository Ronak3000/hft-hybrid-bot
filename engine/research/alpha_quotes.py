"""Use a frozen directional signal to widen only the exposed side of A/S."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal, localcontext
import math
from pathlib import Path

from engine.market_data import L2Book
from engine.simulation.capture_runner import CapturePolicyRunner
from engine.simulation.policies import AvellanedaStoikovPolicy, QuoteTarget
from engine.simulation.queue_simulator import SIMULATION_DECIMAL_CONTEXT, SimulationConfig

from .l2_features import verify_feature_csv
from .lob_alpha import INPUTS, Session, fit_direction_model, load_session, validate_splits


class AlphaWideningPolicy:
    """Consume signals only when their exact depth update is applied in replay."""

    def __init__(
        self, baseline: AvellanedaStoikovPolicy,
        signals: Mapping[tuple[int, int], int], widen_ticks: int,
    ) -> None:
        if type(widen_ticks) is not int or widen_ticks < 0:
            raise ValueError("widen_ticks must be a nonnegative integer")
        if any(signal not in (-1, 0, 1) for signal in signals.values()):
            raise ValueError("signals must be down (-1), flat (0), or up (1)")
        self.baseline = baseline
        self.signals = dict(signals)
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            self._width = baseline.tick_size * widen_ticks
        self._direction = 0
        self.matched_updates = 0
        self.directions: Counter[int] = Counter()

    def on_depth(self, key: tuple[int, int] | None) -> None:
        # A snapshot, gap, or depth update with no feature row clears the signal.
        self._direction = self.signals.get(key, 0) if key is not None else 0
        if key is not None and key in self.signals:
            self.matched_updates += 1
            self.directions[self._direction] += 1

    def quote(self, book: L2Book, inventory: Decimal, received_time_ns: int) -> QuoteTarget:
        base = self.baseline.quote(book, inventory, received_time_ns)
        if not self._direction or not self._width:
            return base
        bid, ask = base.bid_price, base.ask_price
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            if self._direction > 0 and ask is not None:
                ask += self._width
            elif self._direction < 0 and bid is not None:
                bid -= self._width
                if bid <= 0:
                    bid = None
        return QuoteTarget(bid, ask, base.quantity)


def evaluate_alpha_quotes(
    train: list[Session], validation: list[Session],
    test_capture: Path, test_features: Path, *,
    policy: AvellanedaStoikovPolicy, config: SimulationConfig,
    horizon: int, widen_ticks: int, markout_horizons_ns: tuple[int, ...],
) -> dict:
    """Run a paired replay with identical inputs and no test-label access."""
    test = load_session(test_features)
    verify_feature_csv(test_features, test_capture)
    validate_splits({"train": train, "validation": validation, "test": [test]})
    model, _ = fit_direction_model(train, horizon)
    features = [tuple(float(row[name]) for name in INPUTS) for row in test.rows]
    if not all(math.isfinite(value) for row in features for value in row):
        raise ValueError("non-finite test input")
    keys = [(int(row["received_time_ns"]), int(row["update_id"])) for row in test.rows]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate depth event key in test features")
    adjusted = AlphaWideningPolicy(
        replace(policy), dict(zip(keys, model.predict(features).tolist(), strict=True)), widen_ticks
    )
    base_run = CapturePolicyRunner(replace(policy), config, markout_horizons_ns).run(test_capture)
    alpha_run = CapturePolicyRunner(
        adjusted, config, markout_horizons_ns, on_depth=adjusted.on_depth
    ).run(test_capture)
    if base_run.metrics.snapshots != 1 or adjusted.matched_updates != len(keys):
        raise ValueError("paired replay requires one snapshot and every feature update matched")
    if base_run.final_book_digest != alpha_run.final_book_digest:
        raise RuntimeError("paired replays ended on different market states")

    def summarize(run):
        metrics = run.metrics
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            markouts = {}
            for horizon_ns in markout_horizons_ns:
                fills = [item for item in run.attributions if horizon_ns in item.signed_markouts]
                # Subtract spread edge to isolate movement from the mid at fill.
                markouts[str(horizon_ns)] = {
                    "observed_fills": len(fills),
                    "signed_mid_move_pnl": sum((
                        item.signed_markouts[horizon_ns] - item.spread_edge for item in fills
                    ), Decimal(0)) if fills else None,
                }
        return {
            "fills": metrics.fills, "net_pnl": metrics.net_pnl,
            "fees": metrics.signed_fees, "quantity_fill_rate": metrics.quantity_fill_rate,
            "maximum_absolute_inventory": metrics.maximum_absolute_inventory,
            "adverse_selection": markouts,
        }

    return {
        "capture_sha256": test.manifest["source_sha256"],
        "feature_sha256": test.manifest["sha256"],
        "training_feature_sha256": [s.manifest["sha256"] for s in train],
        "validation_feature_sha256": [s.manifest["sha256"] for s in validation],
        "horizon_updates": horizon, "widen_ticks": widen_ticks,
        "matched_updates": adjusted.matched_updates,
        "matched_directions": {
            name: adjusted.directions[direction]
            for direction, name in ((-1, "down"), (0, "flat"), (1, "up"))
        },
        "avellaneda_stoikov": summarize(base_run),
        "alpha_widened": summarize(alpha_run),
    }
