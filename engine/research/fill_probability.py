"""Empirical quote-fill probabilities under the existing L2 replay model."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Decimal, localcontext

from engine.market_data import ApplyStatus, L2Book, parse_binance_delta, parse_binance_snapshot, parse_binance_trade
from engine.simulation import OrderStatus, QueueAwareSimulator, Side, SimulationConfig
from engine.simulation.queue_simulator import SIMULATION_DECIMAL_CONTEXT
from .trade_hawkes import Arrivals


INPUTS = ("side", "log_offset_ticks", "log_spread_ticks",
          "log_displayed_queue", "log_size", "touch_imbalance")


def probe_features(side, offset, spread, displayed, quantity, imbalance):
    return (float(side), math.log1p(offset), math.log1p(float(spread)),
            math.log1p(float(displayed)), math.log1p(float(quantity)), float(imbalance))


class FrozenFillModel:
    """Inference from the training fit and optional validation-only sigmoid."""

    def __init__(self, report):
        import numpy as np

        if tuple(report["inputs"]) != INPUTS or report["target"] != "any_simulated_fill_before_or_at_deadline":
            raise ValueError("unsupported fill forecast schema")
        weights = report["weights"]
        self.mean, self.scale, self.coef = (
            np.asarray(weights[name], dtype=np.float64)
            for name in ("scaler_mean", "scaler_scale", "coef")
        )
        self.bias = float(weights["intercept"])
        self.calibration = weights["validation_sigmoid"]
        if (any(x.shape != (len(INPUTS),) or not np.isfinite(x).all()
                for x in (self.mean, self.scale, self.coef))
                or (self.scale <= 0).any() or not math.isfinite(self.bias)
                or (self.calibration is not None and (
                    len(self.calibration) != 2 or not all(map(math.isfinite, self.calibration))
                ))):
            raise ValueError("invalid fill forecast weights")
        self.offsets = tuple(report["settings"]["offsets"])
        if not self.offsets or any(type(o) is not int or o < 0 for o in self.offsets):
            raise ValueError("invalid fill forecast offset grid")

    def predict(self, features):
        import numpy as np

        logits = ((np.asarray(features) - self.mean) / self.scale) @ self.coef + self.bias
        if self.calibration is not None:
            logits = self.calibration[0] * logits + self.calibration[1]
        return 1 / (1 + np.exp(-np.clip(logits, -50, 50)))


@dataclass(slots=True)
class _Probe:
    deadline_ns: int
    simulator: QueueAwareSimulator
    features: tuple[float, ...]

    def row(self):
        order = self.simulator.orders[1]
        return self.features, int(bool(self.simulator.fills)), order.status is OrderStatus.REJECTED


def probe_session(session: Arrivals, *, config: SimulationConfig, tick_size: Decimal,
                  quantities: tuple[Decimal, ...], horizon_ns: int, stride: int, offsets: tuple[int, ...]):
    """Sample independent, unamended quotes. Exclude all incomplete horizons."""
    if (horizon_ns < 1 or stride < 1 or not offsets or min(offsets) < 0 or not quantities
            or any(not x.is_finite() or x <= 0 for x in (tick_size, *quantities))):
        raise ValueError("invalid probe settings")
    book = L2Book(*session.market)
    ready = None
    last_time = -1
    active: list[_Probe] = []
    rows = []
    decisions = 0
    with session.path.open(encoding="utf-8") as source, localcontext(SIMULATION_DECIMAL_CONTEXT):
        for line in source:
            item = json.loads(line)
            kind, payload, received = item["kind"], item["payload"], item["received_time_ns"]
            if kind == "metadata":
                continue
            if kind == "snapshot":
                if ready is not None:
                    raise ValueError(f"{session.path.name}: probe sampling requires one snapshot")
                ready = received
                book.load_snapshot(parse_binance_snapshot(payload, book.symbol, received))
                continue
            if ready is None or kind not in ("trade", "delta"):
                raise ValueError(f"{session.path.name}: unexpected record {kind}")
            if received < ready:
                if last_time >= ready:
                    raise ValueError(f"{session.path.name}: receive time went backwards")
                if kind == "delta" and book.apply_delta(parse_binance_delta(payload, received)) is ApplyStatus.GAP:
                    raise ValueError(f"{session.path.name}: depth gap in buffered updates")
                continue
            if received < last_time:
                raise ValueError(f"{session.path.name}: receive time went backwards")
            last_time = received
            remaining = []
            for probe in active:
                if probe.deadline_ns < received:
                    # No records occurred between the last event and this
                    # deadline. Process any latency actions, not this next event.
                    probe.simulator.advance_to(probe.deadline_ns, book)
                    rows.append(probe.row())
                else:
                    remaining.append(probe)
            active = remaining
            if kind == "trade":
                trade = parse_binance_trade(payload, received)
                for probe in active:
                    probe.simulator.process_trade(trade, book)
                continue
            for probe in active:
                probe.simulator.advance_to(received, book)
            status = book.apply_delta(parse_binance_delta(payload, received))
            if status is ApplyStatus.GAP:
                raise ValueError(f"{session.path.name}: depth gap")
            if status is not ApplyStatus.APPLIED:
                continue
            decisions += 1
            if (decisions - 1) % stride:
                continue
            bid, ask = book.best_bid, book.best_ask
            if bid is None or ask is None:
                continue
            spread = (ask - bid) / tick_size
            bqty, aqty = book.bids[bid], book.asks[ask]
            imbalance = float((bqty - aqty) / (bqty + aqty))
            for side in (Side.BUY, Side.SELL):
                direction = 1 if side is Side.BUY else -1
                prices = book.bids if side is Side.BUY else book.asks
                touch = bid if side is Side.BUY else ask
                for offset in offsets:
                    price = touch - direction * tick_size * offset
                    if price <= 0:
                        continue
                    for quantity in quantities:
                        features = probe_features(direction, offset, spread, prices.get(price, 0),
                                                  quantity, imbalance)
                        sim = QueueAwareSimulator(config)
                        sim.submit_limit(side, price, quantity, received)
                        sim.advance_to(received, book)
                        active.append(_Probe(received + horizon_ns, sim, features))
        censored = 0
        for probe in active:
            if probe.deadline_ns <= last_time:
                rows.append(probe.row())
            else:
                censored += 1
    return rows, censored


def score_probabilities(actual, predicted):
    import numpy as np

    y, p = np.asarray(actual), np.asarray(predicted)
    clipped = np.clip(p, 1e-12, 1 - 1e-12)
    buckets = np.minimum(9, (p * 10).astype(int))
    return {
        "rows": len(y), "fills": int(y.sum()),
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(-np.mean(y * np.log(clipped) + (1 - y) * np.log1p(-clipped))),
        "reliability": [
            {"decile": i, "count": int(mask.sum()), "mean_prediction": float(p[mask].mean()),
             "observed_rate": float(y[mask].mean())}
            for i in range(10) if (mask := buckets == i).any()
        ],
    }


def evaluate_fill_probabilities(splits, **probe_options):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    prepared = {}
    previous_end, seen, markets = -1, set(), set()
    for split in ("train", "validation", "test"):
        if not splits[split]:
            raise ValueError(f"{split}: provide a capture")
        prepared[split] = []
        for session in splits[split]:
            first, last = session.bounds_ns
            if session.sha256 in seen or first <= previous_end:
                raise ValueError("probe captures must be unique and strictly chronological")
            previous_end = last
            seen.add(session.sha256)
            markets.add(session.market)
            rows, censored = probe_session(session, **probe_options)
            if not rows:
                raise ValueError(f"{session.path.name}: no complete probe outcomes")
            x, y, rejected = zip(*rows)
            prepared[split].append((session, x, y, sum(rejected), censored))
    if len(markets) != 1:
        raise ValueError("probe captures must use the same market")

    def pool(split):
        return np.concatenate([s[1] for s in prepared[split]]), np.concatenate([s[2] for s in prepared[split]])

    x, y = pool("train")
    if len(set(y)) < 2:
        raise ValueError("training probes need both fills and non-fills")
    scaler = StandardScaler().fit(x)
    model = LogisticRegression(solver="newton-cg", random_state=0).fit(scaler.transform(x), y)
    xval, yval = pool("validation")
    calibrator = None
    if min(int(yval.sum()), int((1 - yval).sum())) >= 5:
        logits = model.decision_function(scaler.transform(xval)).reshape(-1, 1)
        calibrator = LogisticRegression(solver="newton-cg", random_state=0).fit(logits, yval)

    def score(features, actual, include_calibrated):
        scaled = scaler.transform(features)
        result = {"train_fill_rate": score_probabilities(actual, np.full(len(actual), y.mean())),
                  "logistic": score_probabilities(actual, model.predict_proba(scaled)[:, 1])}
        if calibrator is not None and include_calibrated:
            logits = model.decision_function(scaled).reshape(-1, 1)
            result["validation_calibrated"] = score_probabilities(
                actual, calibrator.predict_proba(logits)[:, 1])
        return result

    return {
        "inputs": INPUTS, "target": "any_simulated_fill_before_or_at_deadline",
        "calibration_applied": calibrator is not None,
        "weights": {
            "scaler_mean": scaler.mean_.tolist(), "scaler_scale": scaler.scale_.tolist(),
            "coef": model.coef_[0].tolist(), "intercept": float(model.intercept_[0]),
            "validation_sigmoid": [float(calibrator.coef_[0][0]), float(calibrator.intercept_[0])]
            if calibrator is not None else None,
        },
        "sessions": {
            split: [{"capture": session.path.name, "sha256": session.sha256, "rows": len(actual),
                     "fills": sum(actual), "rejected": rejected, "censored": censored,
                     **({} if split == "train" else {"scores": score(features, actual, split == "test")})}
                    for session, features, actual, rejected, censored in groups]
            for split, groups in prepared.items()
        },
        "pooled_test": score(*pool("test"), True),
    }
