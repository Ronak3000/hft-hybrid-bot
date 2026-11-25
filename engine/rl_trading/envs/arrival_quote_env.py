"""Shared continuous action adapter for PPO/SAC on the L2 queue simulator."""

from __future__ import annotations

from bisect import bisect_left
from decimal import Decimal, localcontext
from itertools import groupby

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from engine.research.fill_probability import FrozenFillModel, probe_features
from engine.research.trade_hawkes import Arrivals
from engine.simulation import QuoteTarget
from engine.simulation.queue_simulator import SIMULATION_DECIMAL_CONTEXT
from .queue_replay_env import QueueReplayEnv


OFFSET_TICKS = (0, 1, 4, 16, 64, 256, 1024, 4096, 8192)
SIZE_FRACTIONS = (Decimal(0), Decimal("0.25"), Decimal("0.5"), Decimal(1))


class CausalTradeHistory:
    """Prefix recurrence indexed by strictly earlier local receive timestamps."""

    def __init__(self, arrivals: Arrivals, decay: float, parameters: np.ndarray) -> None:
        self.times: list[int] = []
        self.prefix: list[np.ndarray] = []
        self.params, self.decay = np.asarray(parameters, dtype=np.float64).copy(), decay
        if (self.params.shape != (2, 3) or not np.isfinite(self.params).all()
                or not np.isfinite(decay) or decay <= 0
                or (self.params[:, 0] <= 0).any() or (self.params[:, 1:] < 0).any()):
            raise ValueError("invalid two-sided Hawkes parameters")
        if max(abs(np.linalg.eigvals(self.params[:, 1:] / decay))) >= 1:
            raise ValueError("a stationary Hawkes observation requires a subcritical fit")
        state = np.zeros(2)
        for timestamp, group in groupby(arrivals.trades, key=lambda item: item[0]):
            if self.times:
                state *= np.exp(-decay * (timestamp - self.times[-1]) / 1e9)
            state += np.bincount([side for _, side in group], minlength=2)
            self.times.append(timestamp)
            self.prefix.append(state.copy())

    def intensity(self, timestamp: int) -> np.ndarray:
        i = bisect_left(self.times, timestamp) - 1
        if i < 0:
            return self.params[:, 0].copy()
        decay = np.exp(-self.decay * (timestamp - self.times[i]) / 1e9)
        return self.params[:, 0] + self.params[:, 1:] @ (self.prefix[i] * decay)


class ArrivalQuoteEnv(gym.Wrapper):
    """Pick independent bid and ask offsets, and a shared capped order size."""

    def __init__(self, base: QueueReplayEnv, histories: tuple[CausalTradeHistory, ...],
                 fill_model: FrozenFillModel | None = None, *, hide_fill_signal: bool = False) -> None:
        super().__init__(base)
        if len(histories) != len(base.capture_paths) or not histories:
            raise ValueError("one arrival history is required for every capture")
        self.histories = histories
        self.fill_model = fill_model
        self.hide_fill_signal = hide_fill_signal
        extras = 2 + (2 * len(fill_model.offsets) if fill_model else 0)
        self.action_space = spaces.Box(-1.0, 1.0, (3,), dtype=np.float32)
        self.observation_space = spaces.Box(
            np.r_[base.observation_space.low, np.zeros(extras)].astype(np.float32),
            np.r_[base.observation_space.high, np.ones(extras)].astype(np.float32),
            dtype=np.float32,
        )

    def _extend(self, observation):
        rates = self.histories[self.env.current_capture_index].intensity(
            self.env.current_decision_time_ns
        )
        # Bounded monotonic transform, no validation/test normalization.
        values = rates / (1 + rates)
        if self.fill_model is not None:
            values = np.r_[values, self._fill_profile()]
        return np.r_[observation, values].astype(np.float32)

    def _fill_profile(self):
        model, book = self.fill_model, self.env.book
        if self.hide_fill_signal or book is None or not book.synchronized:
            return np.zeros(2 * len(model.offsets))
        bid, ask = book.best_bid, book.best_ask
        if bid is None or ask is None:
            return np.zeros(2 * len(model.offsets))
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            tick = self.env.tick_size
            spread = (ask - bid) / tick
            bqty, aqty = book.bids[bid], book.asks[ask]
            imbalance = (bqty - aqty) / (bqty + aqty)
            prices = [(direction, offset, touch - direction * tick * offset, depth)
                      for direction, touch, depth in ((1, bid, book.bids), (-1, ask, book.asks))
                      for offset in model.offsets]
            rows = [probe_features(direction, offset, spread, depth.get(price, 0),
                                   self.env.quantity, imbalance)
                    for direction, offset, price, depth in prices]
        valid = np.array([price > 0 for _, _, price, _ in prices])
        return np.where(valid, model.predict(rows), 0.0)

    @staticmethod
    def _choice(value: float, grid: tuple):
        return grid[min(len(grid) - 1, int((value + 1.0) * len(grid) / 2.0))]

    def target(self, action) -> QuoteTarget:
        action = np.asarray(action, dtype=np.float32)
        if not self.action_space.contains(action):
            raise ValueError("expected three finite normalized quote controls in [-1, 1]")
        book = self.env.book
        if book is None or book.best_bid is None or book.best_ask is None:
            raise RuntimeError("reset to a synchronized L2 book before quoting")
        bid_ticks, ask_ticks = (self._choice(float(value), OFFSET_TICKS) for value in action[:2])
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            size = self.env.quantity * self._choice(float(action[2]), SIZE_FRACTIONS)
            if not size:
                return QuoteTarget(None, None, self.env.quantity)
            bid = book.best_bid - self.env.tick_size * bid_ticks
            ask = book.best_ask + self.env.tick_size * ask_ticks
        return QuoteTarget(bid if bid > 0 else None, ask, size)

    def reset(self, **kwargs):
        observation, info = self.env.reset(**kwargs)
        return self._extend(observation), info

    def step_quote_target(self, target: QuoteTarget):
        observation, reward, terminated, truncated, info = self.env.step_quote_target(target)
        # A recording boundary is the terminal state for this finite replay
        # objective. Do not let RL bootstrap from an invalidated market book.
        return self._extend(observation), reward, terminated or truncated, False, info

    def step(self, action):
        return self.step_quote_target(self.target(action))
