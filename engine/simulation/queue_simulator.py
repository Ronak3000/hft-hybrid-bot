"""Conservative, deterministic queue-ahead paper execution.

The simulator consumes aggregated L2 state and public trades. It cannot recover
market-by-order queue position and therefore makes its approximation explicit:
displayed quantity at the quote price is initially ahead, and only matching
public trades reduce it. Displayed cancellations receive no queue credit.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from enum import Enum
from typing import Any

from engine.market_data import L2Book, MarketTrade


SIMULATION_DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


def _decimal(value: Any, field_name: str, *, positive: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal number") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        qualifier = "positive finite" if positive else "finite"
        raise ValueError(f"{field_name} must be {qualifier}")
    return parsed


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    initial_cash: Decimal = Decimal("1000000")
    maker_fee_rate: Decimal = Decimal("0")
    order_latency_ns: int = 0
    cancel_latency_ns: int = 0
    max_abs_inventory: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        initial_cash = _decimal(self.initial_cash, "initial_cash")
        maker_fee_rate = _decimal(self.maker_fee_rate, "maker_fee_rate")
        max_inventory = _decimal(
            self.max_abs_inventory, "max_abs_inventory", positive=True
        )
        if initial_cash < 0:
            raise ValueError("initial_cash must be non-negative")
        if maker_fee_rate <= Decimal("-1"):
            raise ValueError("maker_fee_rate must exceed -1")
        order_latency_ns = _nonnegative_int(self.order_latency_ns, "order_latency_ns")
        cancel_latency_ns = _nonnegative_int(
            self.cancel_latency_ns, "cancel_latency_ns"
        )
        object.__setattr__(self, "initial_cash", initial_cash)
        object.__setattr__(self, "maker_fee_rate", maker_fee_rate)
        object.__setattr__(self, "max_abs_inventory", max_inventory)
        object.__setattr__(self, "order_latency_ns", order_latency_ns)
        object.__setattr__(self, "cancel_latency_ns", cancel_latency_ns)


@dataclass(slots=True)
class SimulatedOrder:
    order_id: int
    side: Side
    price: Decimal
    original_quantity: Decimal
    remaining_quantity: Decimal
    decision_time_ns: int
    activation_time_ns: int
    status: OrderStatus = OrderStatus.PENDING
    queue_ahead: Decimal = Decimal("0")
    rejection_reason: str | None = None
    cancel_effective_time_ns: int | None = None


@dataclass(frozen=True, slots=True)
class Fill:
    order_id: int
    side: Side
    price: Decimal
    quantity: Decimal
    notional: Decimal
    fee: Decimal
    trade_id: int
    trade_time_ms: int
    received_time_ns: int


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    cash: Decimal
    inventory: Decimal
    fees: Decimal
    turnover: Decimal
    net_worth: Decimal


@dataclass(order=True, slots=True)
class _ScheduledAction:
    effective_time_ns: int
    sequence: int
    action: str = field(compare=False)
    order_id: int = field(compare=False)


class QueueAwareSimulator:
    """One-active-quote-per-side simulator with explicit latency and accounting."""

    def __init__(self, config: SimulationConfig | None = None) -> None:
        self.config = config or SimulationConfig()
        self.cash = self.config.initial_cash
        self.inventory = Decimal("0")
        self.fees = Decimal("0")
        self.turnover = Decimal("0")
        self.current_time_ns = 0
        self.orders: dict[int, SimulatedOrder] = {}
        self.fills: list[Fill] = []
        self._actions: list[_ScheduledAction] = []
        self._open_order_ids: dict[Side, int | None] = {
            Side.BUY: None,
            Side.SELL: None,
        }
        self._next_order_id = 1
        self._next_sequence = 0

    def submit_limit(
        self,
        side: Side | str,
        price: Decimal | str | int,
        quantity: Decimal | str | int,
        decision_time_ns: int,
    ) -> int:
        parsed_side = Side(side)
        parsed_price = _decimal(price, "price", positive=True)
        parsed_quantity = _decimal(quantity, "quantity", positive=True)
        self._validate_decision_time(decision_time_ns)
        if self.open_order(parsed_side) is not None:
            raise ValueError(f"an open {parsed_side.value} order already exists")

        order_id = self._next_order_id
        self._next_order_id += 1
        activation_time = decision_time_ns + self.config.order_latency_ns
        self.orders[order_id] = SimulatedOrder(
            order_id=order_id,
            side=parsed_side,
            price=parsed_price,
            original_quantity=parsed_quantity,
            remaining_quantity=parsed_quantity,
            decision_time_ns=decision_time_ns,
            activation_time_ns=activation_time,
        )
        self._open_order_ids[parsed_side] = order_id
        self._schedule(activation_time, "activate", order_id)
        return order_id

    def request_cancel(self, order_id: int, decision_time_ns: int) -> bool:
        self._validate_decision_time(decision_time_ns)
        order = self.orders.get(order_id)
        if order is None or order.status not in {OrderStatus.PENDING, OrderStatus.ACTIVE}:
            return False
        if decision_time_ns < order.decision_time_ns:
            raise ValueError("cancel decision cannot precede order submission")
        if order.cancel_effective_time_ns is not None:
            return False
        order.cancel_effective_time_ns = decision_time_ns + self.config.cancel_latency_ns
        self._schedule(order.cancel_effective_time_ns, "cancel", order_id)
        return True

    def advance_to(self, received_time_ns: int, book: L2Book) -> None:
        timestamp = _nonnegative_int(received_time_ns, "received_time_ns")
        if timestamp < self.current_time_ns:
            raise ValueError("simulation time must be nondecreasing")
        while self._actions and self._actions[0].effective_time_ns <= timestamp:
            action = heapq.heappop(self._actions)
            self.current_time_ns = action.effective_time_ns
            order = self.orders[action.order_id]
            if action.action == "activate":
                self._activate(order, book)
            elif action.action == "cancel" and order.status in {
                OrderStatus.PENDING,
                OrderStatus.ACTIVE,
            }:
                self._close(order, OrderStatus.CANCELED)
        self.current_time_ns = timestamp

    def process_trade(self, trade: MarketTrade, book: L2Book) -> tuple[Fill, ...]:
        if trade.venue != book.venue or trade.symbol != book.symbol:
            raise ValueError("trade identity does not match the active L2 book")
        self.advance_to(trade.received_time_ns, book)
        side = Side.BUY if trade.aggressor_side == "sell" else Side.SELL
        order = self.open_order(side, active_only=True)
        if order is None or not self._trade_reaches_order(trade, order):
            return ()

        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            if self._is_trade_through(trade, order):
                executable = order.remaining_quantity
            else:
                queue_consumed = min(order.queue_ahead, trade.quantity)
                order.queue_ahead -= queue_consumed
                executable = min(
                    order.remaining_quantity, trade.quantity - queue_consumed
                )
            executable = min(executable, self._inventory_capacity(order.side))
        if executable <= 0:
            return ()
        return (self._fill(order, executable, trade),)

    def invalidate_open_orders(self, received_time_ns: int) -> int:
        """Immediately remove quotes when market-data continuity is lost."""
        timestamp = _nonnegative_int(received_time_ns, "received_time_ns")
        if timestamp < self.current_time_ns:
            raise ValueError("simulation time must be nondecreasing")
        self.current_time_ns = timestamp
        invalidated = 0
        for side in Side:
            order = self.open_order(side)
            if order is not None:
                self._close(order, OrderStatus.INVALIDATED)
                invalidated += 1
        return invalidated

    def open_order(
        self, side: Side | str, *, active_only: bool = False
    ) -> SimulatedOrder | None:
        parsed_side = Side(side)
        allowed = {OrderStatus.ACTIVE} if active_only else {
            OrderStatus.PENDING,
            OrderStatus.ACTIVE,
        }
        order_id = self._open_order_ids[parsed_side]
        if order_id is None:
            return None
        order = self.orders[order_id]
        return order if order.status in allowed else None

    def account(self, mark_price: Decimal | str | int) -> AccountSnapshot:
        mark = _decimal(mark_price, "mark_price", positive=True)
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            return AccountSnapshot(
                cash=self.cash,
                inventory=self.inventory,
                fees=self.fees,
                turnover=self.turnover,
                net_worth=self.cash + self.inventory * mark,
            )

    def _activate(self, order: SimulatedOrder, book: L2Book) -> None:
        if order.status is not OrderStatus.PENDING:
            return
        if not book.synchronized:
            self._reject(order, "book_not_synchronized")
            return
        best_bid = book.best_bid
        best_ask = book.best_ask
        if best_bid is None or best_ask is None:
            self._reject(order, "empty_book")
            return
        if order.side is Side.BUY:
            if order.price >= best_ask:
                self._reject(order, "would_take_liquidity")
                return
            order.queue_ahead = book.bids.get(order.price, Decimal("0"))
        else:
            if order.price <= best_bid:
                self._reject(order, "would_take_liquidity")
                return
            order.queue_ahead = book.asks.get(order.price, Decimal("0"))
        order.status = OrderStatus.ACTIVE

    def _fill(self, order: SimulatedOrder, quantity: Decimal, trade: MarketTrade) -> Fill:
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            notional = order.price * quantity
            fee = notional * self.config.maker_fee_rate
            if order.side is Side.BUY:
                self.cash -= notional + fee
                self.inventory += quantity
            else:
                self.cash += notional - fee
                self.inventory -= quantity
            self.fees += fee
            self.turnover += notional
            order.remaining_quantity -= quantity
        if order.remaining_quantity == 0:
            self._close(order, OrderStatus.FILLED)
        fill = Fill(
            order_id=order.order_id,
            side=order.side,
            price=order.price,
            quantity=quantity,
            notional=notional,
            fee=fee,
            trade_id=trade.trade_id,
            trade_time_ms=trade.trade_time_ms,
            received_time_ns=trade.received_time_ns,
        )
        self.fills.append(fill)
        return fill

    def _inventory_capacity(self, side: Side) -> Decimal:
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            if side is Side.BUY:
                return max(
                    self.config.max_abs_inventory - self.inventory, Decimal("0")
                )
            return max(self.config.max_abs_inventory + self.inventory, Decimal("0"))

    @staticmethod
    def _trade_reaches_order(trade: MarketTrade, order: SimulatedOrder) -> bool:
        if order.side is Side.BUY:
            return trade.aggressor_side == "sell" and trade.price <= order.price
        return trade.aggressor_side == "buy" and trade.price >= order.price

    @staticmethod
    def _is_trade_through(trade: MarketTrade, order: SimulatedOrder) -> bool:
        if order.side is Side.BUY:
            return trade.price < order.price
        return trade.price > order.price

    def _schedule(self, effective_time_ns: int, action: str, order_id: int) -> None:
        heapq.heappush(
            self._actions,
            _ScheduledAction(effective_time_ns, self._next_sequence, action, order_id),
        )
        self._next_sequence += 1

    def _validate_decision_time(self, decision_time_ns: int) -> None:
        timestamp = _nonnegative_int(decision_time_ns, "decision_time_ns")
        if timestamp < self.current_time_ns:
            raise ValueError("decision time cannot precede simulation time")

    def _reject(self, order: SimulatedOrder, reason: str) -> None:
        order.rejection_reason = reason
        self._close(order, OrderStatus.REJECTED)

    def _close(self, order: SimulatedOrder, status: OrderStatus) -> None:
        order.status = status
        if self._open_order_ids[order.side] == order.order_id:
            self._open_order_ids[order.side] = None
