"""Gymnasium environment backed by verified L2 captures and queue simulation."""

from __future__ import annotations

import json
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Iterator

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from engine.market_data import (
    ApplyStatus,
    L2Book,
    SchemaError,
    parse_binance_delta,
    parse_binance_snapshot,
    parse_binance_trade,
    verify_capture,
)
from engine.simulation import (
    OrderStatus,
    QuoteTarget,
    QueueAwareSimulator,
    Side,
    SimulationConfig,
    quote_target_around,
    reconcile_quote_target,
)
from engine.simulation.queue_simulator import SIMULATION_DECIMAL_CONTEXT, _decimal


class QueueReplayEnv(gym.Env[np.ndarray, int]):
    """One capture segment per episode with depth-update decision points.

    Action zero leaves the market. Other actions choose a symmetric half-width
    and center skew in integer ticks. The selected target persists between depth
    decisions and is reconciled after trades using the shared simulator rules.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        capture_paths: tuple[str | Path, ...],
        *,
        tick_size: Decimal | str,
        quantity: Decimal | str,
        simulation_config: SimulationConfig | None = None,
        maximum_half_spread_ticks: int = 5,
        maximum_absolute_skew_ticks: int = 2,
        reward_scale: Decimal | str = Decimal("1"),
        inventory_penalty_per_second: Decimal | str = Decimal("0"),
    ) -> None:
        super().__init__()
        if not capture_paths:
            raise ValueError("at least one training capture is required")
        self.capture_paths = tuple(Path(path) for path in capture_paths)
        hashes: set[str] = set()
        ordered_hashes: list[str] = []
        segment_counts: list[int] = []
        for path in self.capture_paths:
            capture_hash = verify_capture(path)["sha256"]
            if capture_hash in hashes:
                raise ValueError("training captures must have unique content")
            hashes.add(capture_hash)
            ordered_hashes.append(capture_hash)
            segment_counts.append(self._count_segments(path))
        self.capture_hashes = tuple(ordered_hashes)
        self.capture_segment_counts = tuple(segment_counts)
        self._episodes = tuple(
            (capture_index, segment_index)
            for capture_index, count in enumerate(self.capture_segment_counts)
            for segment_index in range(count)
        )
        self.tick_size = _decimal(tick_size, "tick_size", positive=True)
        self.quantity = _decimal(quantity, "quantity", positive=True)
        self.config = simulation_config or SimulationConfig()
        self.maximum_half_spread_ticks = _positive_int(
            maximum_half_spread_ticks, "maximum_half_spread_ticks"
        )
        self.maximum_absolute_skew_ticks = _nonnegative_int(
            maximum_absolute_skew_ticks, "maximum_absolute_skew_ticks"
        )
        self.reward_scale = _decimal(reward_scale, "reward_scale", positive=True)
        self.inventory_penalty_per_second = _decimal(
            inventory_penalty_per_second, "inventory_penalty_per_second"
        )
        if self.inventory_penalty_per_second < 0:
            raise ValueError("inventory_penalty_per_second must be non-negative")

        skew_choices = 2 * self.maximum_absolute_skew_ticks + 1
        self.action_space = spaces.Discrete(
            1 + self.maximum_half_spread_ticks * skew_choices
        )
        self.observation_space = spaces.Box(
            low=np.array(
                [0, -1, -10, -20, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                dtype=np.float32,
            ),
            high=np.array(
                [20, 1, 10, 20, 1, 1, 1, 1, 10, 1, 1, 1, 10, 1],
                dtype=np.float32,
            ),
            dtype=np.float32,
        )

        self._episode_number = 0
        self._source: Any = None
        self._records: Iterator[tuple[int, dict[str, Any]]] | None = None
        self._pending_record: tuple[int, dict[str, Any]] | None = None
        self.book: L2Book | None = None
        self.simulator = QueueAwareSimulator(self.config)
        self.current_capture_index = 0
        self.current_segment_index = 0
        self.current_capture_path = self.capture_paths[0]
        self.current_decision_time_ns = 0
        self._previous_mid = Decimal("0")
        self._previous_net_worth = self.config.initial_cash
        self._last_action = 0
        self._episode_done = True
        self._steps = 0

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        self.close()
        requested_capture = (
            None if options is None else options.get("capture_index")
        )
        requested_segment = (
            None if options is None else options.get("segment_index")
        )
        if requested_capture is None and requested_segment is not None:
            raise ValueError("segment_index requires capture_index")
        if requested_capture is None:
            index, segment_index = self._episodes[
                self._episode_number % len(self._episodes)
            ]
        else:
            index = _nonnegative_int(requested_capture, "capture_index")
            if index >= len(self.capture_paths):
                raise ValueError("capture_index is outside the training capture list")
            segment_index = (
                0
                if requested_segment is None
                else _nonnegative_int(requested_segment, "segment_index")
            )
            if segment_index >= self.capture_segment_counts[index]:
                raise ValueError("segment_index is outside the selected capture")
        self._episode_number += 1
        self.current_capture_index = index
        self.current_segment_index = segment_index
        self.current_capture_path = self.capture_paths[index]
        self.simulator = QueueAwareSimulator(self.config)
        self._source = self.current_capture_path.open("r", encoding="utf-8")
        self._records = self._iter_records(self._source)
        self._pending_record = None
        self.book = None
        self._last_action = 0
        self._episode_done = False
        self._steps = 0
        try:
            self._initialize_to_first_decision()
            mid = self._mid()
            self._previous_mid = mid
            self._previous_net_worth = self.simulator.account(mid).net_worth
            observation = self._observation(mid)
        except Exception:
            self.close()
            raise
        return observation, self._info("reset", ())

    def step(
        self, action: int
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self._episode_done:
            raise RuntimeError("step called after the episode ended; call reset")
        parsed_action = self._parse_action(action)
        target = self._target(parsed_action)
        assert self.book is not None
        reconcile_quote_target(
            self.simulator, self.book, target, self.current_decision_time_ns
        )
        fill_start = len(self.simulator.fills)
        previous_time = self.current_decision_time_ns
        truncated, reason = self._advance_to_next_decision(target)
        mid = self._mid_or_previous()
        account = self.simulator.account(mid)
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            elapsed_seconds = Decimal(
                max(self.current_decision_time_ns - previous_time, 0)
            ) / Decimal("1000000000")
            inventory_ratio = (
                self.simulator.inventory / self.config.max_abs_inventory
            )
            risk_penalty = (
                self.inventory_penalty_per_second
                * inventory_ratio
                * inventory_ratio
                * elapsed_seconds
            )
            reward_decimal = (
                account.net_worth - self._previous_net_worth - risk_penalty
            ) / self.reward_scale
        self._previous_net_worth = account.net_worth
        self._last_action = parsed_action
        self._steps += 1
        if truncated:
            self._invalidate_at_end()
        observation = self._observation(mid)
        fills = tuple(self.simulator.fills[fill_start:])
        self._episode_done = truncated
        info = self._info(reason, fills)
        info["inventory_penalty"] = str(risk_penalty)
        if truncated:
            self.close()
        return observation, float(reward_decimal), False, truncated, info

    def action_parameters(self, action: int) -> dict[str, int | bool]:
        parsed = self._parse_action(action)
        if parsed == 0:
            return {"quote": False, "half_spread_ticks": 0, "skew_ticks": 0}
        choices = 2 * self.maximum_absolute_skew_ticks + 1
        offset = parsed - 1
        return {
            "quote": True,
            "half_spread_ticks": offset // choices + 1,
            "skew_ticks": offset % choices - self.maximum_absolute_skew_ticks,
        }

    def close(self) -> None:
        if self._source is not None:
            self._source.close()
            self._source = None

    def _initialize_to_first_decision(self) -> None:
        assert self._records is not None
        decision_start_ns: int | None = None
        segment_index = -1
        for line_number, record in self._records:
            kind = record["kind"]
            payload = record["payload"]
            received = record["received_time_ns"]
            if kind == "metadata":
                if self.book is not None:
                    raise SchemaError("capture contains multiple metadata records")
                self.book = L2Book(payload["venue"], payload["symbol"])
                continue
            if self.book is None:
                raise SchemaError(f"{kind} appears before metadata")
            if kind == "snapshot":
                segment_index += 1
                if segment_index < self.current_segment_index:
                    continue
                if segment_index > self.current_segment_index:
                    raise SchemaError("selected segment has no causal decision")
                self.book.load_snapshot(
                    parse_binance_snapshot(payload, self.book.symbol, received)
                )
                decision_start_ns = received
                continue
            if segment_index < self.current_segment_index:
                continue
            if decision_start_ns is None:
                raise SchemaError(f"{kind} appears before a snapshot")
            if received < decision_start_ns:
                if kind == "delta":
                    status = self.book.apply_delta(
                        parse_binance_delta(payload, received)
                    )
                    if status is ApplyStatus.GAP:
                        raise SchemaError("depth gap during snapshot warmup")
                elif kind != "trade":
                    raise SchemaError(
                        f"unsupported warmup record on line {line_number}: {kind}"
                    )
                continue
            if not self.book.synchronized:
                raise SchemaError("capture is not synchronized at decision start")
            self._pending_record = (line_number, record)
            self.current_decision_time_ns = decision_start_ns
            self.simulator.advance_to(decision_start_ns, self.book)
            return
        raise SchemaError("capture ended before the first causal decision")

    def _advance_to_next_decision(self, target: QuoteTarget) -> tuple[bool, str]:
        assert self.book is not None
        while True:
            item = self._next_record()
            if item is None:
                return True, "end_of_capture"
            line_number, record = item
            kind = record["kind"]
            payload = record["payload"]
            received = record["received_time_ns"]
            if received < self.simulator.current_time_ns:
                raise SchemaError(
                    "local receive time regressed after environment activation"
                )
            if kind == "delta":
                self.simulator.advance_to(received, self.book)
                status = self.book.apply_delta(parse_binance_delta(payload, received))
                if status is ApplyStatus.APPLIED:
                    self.current_decision_time_ns = received
                    return False, "depth_decision"
                if status is ApplyStatus.GAP:
                    self.current_decision_time_ns = received
                    self.simulator.invalidate_open_orders(received)
                    return True, "depth_gap"
            elif kind == "trade":
                trade = parse_binance_trade(payload, received)
                self.simulator.process_trade(trade, self.book)
                reconcile_quote_target(self.simulator, self.book, target, received)
                self.current_decision_time_ns = received
            elif kind in {"gap", "trade_gap", "disconnect"}:
                self.current_decision_time_ns = received
                self.simulator.invalidate_open_orders(received)
                return True, kind
            elif kind == "snapshot":
                boundary = max(received, self.simulator.current_time_ns)
                self.current_decision_time_ns = boundary
                self.simulator.invalidate_open_orders(boundary)
                return True, "new_snapshot_segment"
            elif kind == "metadata":
                raise SchemaError("capture contains multiple metadata records")
            else:
                raise SchemaError(
                    f"unsupported record on line {line_number}: {kind}"
                )

    def _next_record(self) -> tuple[int, dict[str, Any]] | None:
        if self._pending_record is not None:
            item = self._pending_record
            self._pending_record = None
            return item
        assert self._records is not None
        return next(self._records, None)

    def _target(self, action: int) -> QuoteTarget:
        parameters = self.action_parameters(action)
        if not parameters["quote"]:
            return QuoteTarget(None, None, self.quantity)
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            center = self._mid() + self.tick_size * parameters["skew_ticks"]
            half_width = self.tick_size * parameters["half_spread_ticks"]
        return quote_target_around(
            center, half_width, self.tick_size, self.quantity
        )

    def _observation(self, mid: Decimal) -> np.ndarray:
        assert self.book is not None
        best_bid = self.book.best_bid
        best_ask = self.book.best_ask
        if best_bid is None or best_ask is None:
            raise SchemaError("cannot observe an empty L2 book")
        bid_quantity = self.book.bids[best_bid]
        ask_quantity = self.book.asks[best_ask]
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            total_quantity = bid_quantity + ask_quantity
            imbalance = (
                (bid_quantity - ask_quantity) / total_quantity
                if total_quantity > 0
                else Decimal("0")
            )
            microprice = (
                best_ask * bid_quantity + best_bid * ask_quantity
            ) / total_quantity
            market_and_account = (
                (best_ask - best_bid) / self.tick_size,
                imbalance,
                (microprice - mid) / self.tick_size,
                (mid - self._previous_mid) / self.tick_size,
                self.simulator.inventory / self.config.max_abs_inventory,
                Decimal(self._last_action)
                / Decimal(int(self.action_space.n) - 1),
            )
            bid_state = self._order_observation(Side.BUY, bid_quantity)
            ask_state = self._order_observation(Side.SELL, ask_quantity)
            values = market_and_account + bid_state + ask_state
        bounds = (
            (0, 20),
            (-1, 1),
            (-10, 10),
            (-20, 20),
            (-1, 1),
            (0, 1),
            (0, 1),
            (0, 1),
            (0, 10),
            (0, 1),
            (0, 1),
            (0, 1),
            (0, 10),
            (0, 1),
        )
        clipped = [
            max(low, min(high, float(value)))
            for value, (low, high) in zip(values, bounds)
        ]
        self._previous_mid = mid
        return np.asarray(clipped, dtype=np.float32)

    def _order_observation(
        self, side: Side, reference_quantity: Decimal
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        order = self.simulator.open_order(side)
        if order is None:
            return (Decimal("0"),) * 4
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            queue_ratio = (
                order.queue_ahead / reference_quantity
                if reference_quantity > 0
                else Decimal("0")
            )
        return (
            Decimal("1"),
            Decimal(int(order.status is OrderStatus.ACTIVE)),
            queue_ratio,
            Decimal(int(order.cancel_effective_time_ns is not None)),
        )

    def _mid(self) -> Decimal:
        assert self.book is not None
        if not self.book.synchronized:
            raise SchemaError("cannot calculate mid from an unsynchronized book")
        best_bid = self.book.best_bid
        best_ask = self.book.best_ask
        if best_bid is None or best_ask is None:
            raise SchemaError("cannot calculate mid from an empty book")
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            return (best_bid + best_ask) / Decimal("2")

    def _mid_or_previous(self) -> Decimal:
        if self.book is not None and self.book.synchronized:
            return self._mid()
        return self._previous_mid

    def _parse_action(self, action: Any) -> int:
        if isinstance(action, np.ndarray):
            if action.shape != ():
                raise ValueError("action must be a scalar discrete index")
            action = action.item()
        if isinstance(action, bool) or not isinstance(action, (int, np.integer)):
            raise ValueError("action must be an integer")
        parsed = int(action)
        if not self.action_space.contains(parsed):
            raise ValueError("action is outside the discrete action space")
        return parsed

    def _info(self, reason: str, fills: tuple[Any, ...]) -> dict[str, Any]:
        mid = self._mid_or_previous()
        account = self.simulator.account(mid)
        statuses = tuple(order.status for order in self.simulator.orders.values())
        return {
            "capture_file": self.current_capture_path.name,
            "capture_sha256": self.capture_hashes[self.current_capture_index],
            "capture_segment_index": self.current_segment_index,
            "capture_segment_count": self.capture_segment_counts[
                self.current_capture_index
            ],
            "decision_time_ns": self.current_decision_time_ns,
            "episode_steps": self._steps,
            "reason": reason,
            "fills_this_step": len(fills),
            "total_fills": len(self.simulator.fills),
            "submitted_orders": len(statuses),
            "active_orders": statuses.count(OrderStatus.ACTIVE),
            "pending_orders": statuses.count(OrderStatus.PENDING),
            "filled_orders": statuses.count(OrderStatus.FILLED),
            "canceled_orders": statuses.count(OrderStatus.CANCELED),
            "rejected_orders": statuses.count(OrderStatus.REJECTED),
            "invalidated_orders": statuses.count(OrderStatus.INVALIDATED),
            "cash": str(account.cash),
            "inventory": str(account.inventory),
            "fees": str(account.fees),
            "turnover": str(account.turnover),
            "net_worth": str(account.net_worth),
        }

    def _invalidate_at_end(self) -> None:
        if self.book is not None:
            self.simulator.invalidate_open_orders(self.simulator.current_time_ns)

    @staticmethod
    def _iter_records(source: Any) -> Iterator[tuple[int, dict[str, Any]]]:
        for line_number, line in enumerate(source, start=1):
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise TypeError
                if not {"kind", "payload", "received_time_ns"} <= record.keys():
                    raise TypeError
                if not isinstance(record["payload"], dict):
                    raise TypeError
                yield line_number, record
            except (json.JSONDecodeError, TypeError) as exc:
                raise SchemaError(
                    f"invalid capture record on line {line_number}"
                ) from exc

    @classmethod
    def _count_segments(cls, path: Path) -> int:
        with path.open("r", encoding="utf-8") as source:
            count = sum(
                record["kind"] == "snapshot"
                for _, record in cls._iter_records(source)
            )
        if count == 0:
            raise SchemaError(f"capture has no snapshot: {path.name}")
        return count


def _positive_int(value: Any, field: str) -> int:
    parsed = _nonnegative_int(value, field)
    if parsed == 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{field} must be a non-negative integer")
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return parsed
