"""Two-sided Hawkes calibration from observed public trade arrivals, not L3."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
import json
from pathlib import Path

import numpy as np

from engine.market_data import parse_binance_trade, verify_capture


@dataclass(frozen=True, slots=True)
class Arrivals:
    path: Path
    sha256: str
    market: tuple[str, str]
    trades: tuple[tuple[int, int], ...]
    capture_bounds_ns: tuple[int, int] | None = None

    @property
    def bounds_ns(self) -> tuple[int, int]:
        return self.capture_bounds_ns or (self.trades[0][0], self.trades[-1][0])


def load_arrivals(path: Path) -> Arrivals:
    manifest = verify_capture(path)
    metadata = manifest["metadata"]
    market = (metadata["venue"], metadata["symbol"])
    ids = None
    trades = []
    first, last = None, None
    with path.open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            if record["kind"] in {"disconnect", "trade_gap", "gap"}:
                raise ValueError(f"{path.name}: arrival fit requires uninterrupted data")
            if record["kind"] in {"snapshot", "delta", "trade"}:
                received = record["received_time_ns"]
                first = received if first is None else min(first, received)
                last = received if last is None else max(last, received)
            if record["kind"] != "trade":
                continue
            trade = parse_binance_trade(record["payload"], record["received_time_ns"])
            if market != (trade.venue, trade.symbol):
                raise ValueError(f"{path.name}: trade identity differs from capture")
            if ids is not None and trade.trade_id != ids + 1:
                raise ValueError(f"{path.name}: trade IDs must be consecutive")
            if trades and trade.received_time_ns < trades[-1][0]:
                raise ValueError(f"{path.name}: trade receive time went backwards")
            ids = trade.trade_id
            trades.append((trade.received_time_ns, int(trade.aggressor_side == "sell")))
    if len(trades) < 3 or trades[0][0] == trades[-1][0]:
        raise ValueError(f"{path.name}: insufficient trade-time coverage")
    return Arrivals(path, manifest["sha256"], market, tuple(trades), (first, last))


def sufficient_statistics(arrivals: Arrivals, decay: float):
    """History matrix and integrated basis for the conditional likelihood."""
    if not np.isfinite(decay) or decay <= 0:
        raise ValueError("decay must be positive and finite")
    origin, end = arrivals.trades[0][0], arrivals.trades[-1][0]
    duration = (end - origin) / 1e9
    history = np.zeros(2)
    integral = np.zeros(2)
    features, counts = [], []
    previous_time = 0.0
    for timestamp, group in groupby(arrivals.trades, key=lambda item: item[0]):
        seconds = (timestamp - origin) / 1e9
        history *= np.exp(-decay * (seconds - previous_time))
        arrivals_at_time = np.bincount([side for _, side in group], minlength=2)
        if timestamp != origin:  # condition on the opening arrivals
            features.append([1.0, *history])
            counts.append(arrivals_at_time)
        # Same-time prints share the same pre-arrival intensity.
        history += arrivals_at_time
        integral += arrivals_at_time * (-np.expm1(-decay * (duration - seconds))) / decay
        previous_time = seconds
    return np.asarray(features), np.asarray(counts), np.array([duration, *integral])


def evaluate_arrivals(train: list[Arrivals], validation: list[Arrivals], test: list[Arrivals],
                      decay: float) -> dict:
    from scipy.optimize import minimize

    end = -1
    seen = set()
    markets = set()
    splits = {"train": train, "validation": validation, "test": test}
    for name, sessions in splits.items():
        if not sessions:
            raise ValueError(f"{name}: provide a capture")
        for session in sessions:
            first, last = session.bounds_ns
            if session.sha256 in seen or first <= end:
                raise ValueError("arrival sessions are reused, overlapping, or out of order")
            seen.add(session.sha256)
            markets.add(session.market)
            end = last
    if len(markets) != 1:
        raise ValueError("all arrival sessions must use the same market")
    stats = [sufficient_statistics(s, decay) for s in train]
    x = np.concatenate([part[0] for part in stats])
    y = np.concatenate([part[1] for part in stats])
    exposure = np.sum([part[2] for part in stats], axis=0)
    poisson = y.sum(axis=0) / exposure[0]
    if (poisson <= 0).any():
        raise ValueError("train needs observed arrivals on both sides")
    parameters = []
    for side in range(2):
        def objective(p):
            rates = x @ p
            return float(exposure @ p - y[:, side] @ np.log(rates)), exposure - x.T @ (y[:, side] / rates)
        fit = minimize(objective, [poisson[side], 0.0, 0.0], jac=True,
                       bounds=[(1e-8, None), (0.0, None), (0.0, None)], method="L-BFGS-B")
        if not fit.success:
            raise ValueError(f"Hawkes calibration failed: {fit.message}")
        parameters.append(fit.x)
    params = np.asarray(parameters)
    radius = float(max(abs(np.linalg.eigvals(params[:, 1:] / decay))))
    matrix0 = np.column_stack((poisson, np.zeros((2, 2))))

    def score(session):
        features, labels, basis = sufficient_statistics(session, decay)
        count = int(labels.sum())
        def log_likelihood(theta):
            return float(((labels * np.log(features @ theta.T)).sum() - (theta @ basis).sum()) / count)
        return {"capture": session.path.name, "sha256": session.sha256, "scored_trades": count,
                "seconds": float(basis[0]), "hawkes_log_likelihood_per_trade": log_likelihood(params),
                "poisson_log_likelihood_per_trade": log_likelihood(matrix0)}

    return {"event_clock": "local_receive_ns", "event_order": ["aggressive_buy", "aggressive_sell"],
            "decay_per_second": decay, "target_rows_baseline_then_source_amplitudes": params.tolist(),
            "poisson_rates_per_second": poisson.tolist(), "branching_spectral_radius": radius,
            "subcritical": radius < 1, "train": [score(s) for s in train],
            "validation": [score(s) for s in validation], "test": [score(s) for s in test]}
