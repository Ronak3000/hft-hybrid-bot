"""Stream verified L2/trade captures through deterministic quote policies."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from engine.market_data import (
    ApplyStatus,
    L2Book,
    MarketTrade,
    SchemaError,
    parse_binance_delta,
    parse_binance_snapshot,
    parse_binance_trade,
    verify_capture,
)

from .policies import QuotePolicy
from .queue_simulator import (
    SIMULATION_DECIMAL_CONTEXT,
    AccountSnapshot,
    Fill,
    OrderStatus,
    QueueAwareSimulator,
    Side,
    SimulationConfig,
)


@dataclass(slots=True)
class FillAttribution:
    fill: Fill
    mid_at_fill: Decimal
    spread_edge: Decimal
    signed_markouts: dict[int, Decimal] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReplayMetrics:
    snapshots: int
    applied_deltas: int
    stale_deltas: int
    public_trades: int
    warmup_trades: int
    fills: int
    submitted_orders: int
    canceled_orders: int
    rejected_orders: int
    invalidated_orders: int
    open_orders_at_end: int
    net_pnl: Decimal
    gross_pnl_before_fees: Decimal
    signed_fees: Decimal
    turnover: Decimal
    filled_quantity: Decimal
    submitted_quantity: Decimal
    quantity_fill_rate: Decimal
    maximum_absolute_inventory: Decimal
    final_account: AccountSnapshot


@dataclass(frozen=True, slots=True)
class CaptureRunResult:
    metrics: ReplayMetrics
    attributions: tuple[FillAttribution, ...]
    final_book_digest: str


class CapturePolicyRunner:
    """Replay one capture without allowing decisions during snapshot warmup."""

    def __init__(
        self,
        policy: QuotePolicy,
        config: SimulationConfig | None = None,
        markout_horizons_ns: tuple[int, ...] = (),
    ) -> None:
        if any(
            isinstance(horizon, bool)
            or not isinstance(horizon, int)
            or horizon <= 0
            for horizon in markout_horizons_ns
        ):
            raise ValueError("markout horizons must be positive integer nanoseconds")
        if len(markout_horizons_ns) != len(set(markout_horizons_ns)):
            raise ValueError("markout horizons must be unique")
        self.policy = policy
        self.simulator = QueueAwareSimulator(config)
        self.markout_horizons_ns = tuple(sorted(markout_horizons_ns))
        self._attributions: list[FillAttribution] = []
        self._pending_markouts: dict[int, deque[FillAttribution]] = {
            horizon: deque() for horizon in self.markout_horizons_ns
        }
        self._maximum_absolute_inventory = Decimal("0")
        self._has_run = False

    def run(self, capture_path: str | Path) -> CaptureRunResult:
        verify_capture(capture_path)
        if self._has_run:
            raise RuntimeError("a CapturePolicyRunner instance can only run once")
        self._has_run = True
        book: L2Book | None = None
        decision_start_ns: int | None = None
        trading_enabled = False
        snapshots = applied = stale = public_trades = warmup_trades = 0

        with Path(capture_path).open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                try:
                    record = json.loads(line)
                    kind = record["kind"]
                    payload = record["payload"]
                    received = record["received_time_ns"]
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    raise SchemaError(
                        f"invalid capture record on line {line_number}"
                    ) from exc

                if kind == "metadata":
                    if book is not None:
                        raise SchemaError("capture contains multiple metadata records")
                    book = L2Book(payload["venue"], payload["symbol"])
                    continue
                if book is None:
                    raise SchemaError(f"{kind} appears before metadata")

                if kind == "snapshot":
                    boundary_time = max(received, self.simulator.current_time_ns)
                    self.simulator.invalidate_open_orders(boundary_time)
                    book.load_snapshot(
                        parse_binance_snapshot(payload, book.symbol, received)
                    )
                    snapshots += 1
                    decision_start_ns = received
                    trading_enabled = False
                    continue

                if (
                    not trading_enabled
                    and decision_start_ns is not None
                    and received >= decision_start_ns
                    and book.synchronized
                ):
                    self.simulator.advance_to(decision_start_ns, book)
                    self._observe_markouts(decision_start_ns, book)
                    self._reconcile_quotes(decision_start_ns, book)
                    trading_enabled = True

                if kind == "delta":
                    delta = parse_binance_delta(payload, received)
                    if trading_enabled:
                        self._require_nondecreasing(received)
                        self.simulator.advance_to(received, book)
                    status = book.apply_delta(delta)
                    if status is ApplyStatus.APPLIED:
                        applied += 1
                        if trading_enabled:
                            self._observe_markouts(received, book)
                            self._reconcile_quotes(received, book)
                    elif status is ApplyStatus.STALE:
                        stale += 1
                    elif status is ApplyStatus.GAP:
                        trading_enabled = False
                        decision_start_ns = None
                        self.simulator.invalidate_open_orders(
                            max(received, self.simulator.current_time_ns)
                        )
                elif kind == "trade":
                    public_trades += 1
                    trade = parse_binance_trade(payload, received)
                    if not trading_enabled:
                        warmup_trades += 1
                        continue
                    self._require_nondecreasing(received)
                    before = len(self.simulator.fills)
                    mid = _mid(book)
                    self.simulator.process_trade(trade, book)
                    self._record_new_fills(before, mid)
                    self._observe_markouts(received, book)
                    self._reconcile_quotes(received, book)
                elif kind in {"gap", "trade_gap", "disconnect"}:
                    if trading_enabled:
                        self._require_nondecreasing(received)
                        self.simulator.invalidate_open_orders(received)
                    trading_enabled = False
                    decision_start_ns = None
                else:
                    raise SchemaError(
                        f"unsupported record kind on line {line_number}: {kind}"
                    )

        if book is None:
            raise SchemaError("capture has no metadata record")
        final_mid = _mid(book)
        if final_mid is None:
            raise SchemaError("capture has no synchronized final mid price")
        account = self.simulator.account(final_mid)
        metrics = self._metrics(
            account, snapshots, applied, stale, public_trades, warmup_trades
        )
        return CaptureRunResult(
            metrics=metrics,
            attributions=tuple(self._attributions),
            final_book_digest=book.state_digest(),
        )

    def _reconcile_quotes(self, received_time_ns: int, book: L2Book) -> None:
        target = self.policy.quote(
            book, self.simulator.inventory, received_time_ns
        )
        desired = {
            Side.BUY: target.bid_price,
            Side.SELL: target.ask_price,
        }
        if self.simulator.inventory >= self.simulator.config.max_abs_inventory:
            desired[Side.BUY] = None
        if self.simulator.inventory <= -self.simulator.config.max_abs_inventory:
            desired[Side.SELL] = None

        for side in Side:
            order = self.simulator.open_order(side)
            price = desired[side]
            if order is not None:
                if price is None or order.price != price:
                    self.simulator.request_cancel(order.order_id, received_time_ns)
                continue
            if price is not None:
                self.simulator.submit_limit(
                    side, price, target.quantity, received_time_ns
                )
        # Zero-latency actions take effect just after this observed event. They
        # cannot fill on the event that caused the decision, but they are ready
        # for the next record at the same or a later timestamp.
        self.simulator.advance_to(received_time_ns, book)

    def _record_new_fills(self, first_index: int, mid: Decimal) -> None:
        for fill in self.simulator.fills[first_index:]:
            with localcontext(SIMULATION_DECIMAL_CONTEXT):
                if fill.side is Side.BUY:
                    spread_edge = (mid - fill.price) * fill.quantity
                else:
                    spread_edge = (fill.price - mid) * fill.quantity
            attribution = FillAttribution(fill, mid, spread_edge)
            self._attributions.append(attribution)
            for pending in self._pending_markouts.values():
                pending.append(attribution)
            self._maximum_absolute_inventory = max(
                self._maximum_absolute_inventory, abs(self.simulator.inventory)
            )

    def _observe_markouts(self, received_time_ns: int, book: L2Book) -> None:
        mid = _mid(book)
        if mid is None:
            return
        for horizon, pending in self._pending_markouts.items():
            while (
                pending
                and received_time_ns
                >= pending[0].fill.received_time_ns + horizon
            ):
                attribution = pending.popleft()
                sign = Decimal("1") if attribution.fill.side is Side.BUY else Decimal("-1")
                with localcontext(SIMULATION_DECIMAL_CONTEXT):
                    attribution.signed_markouts[horizon] = (
                        sign
                        * (mid - attribution.fill.price)
                        * attribution.fill.quantity
                    )

    def _metrics(
        self,
        account: AccountSnapshot,
        snapshots: int,
        applied: int,
        stale: int,
        public_trades: int,
        warmup_trades: int,
    ) -> ReplayMetrics:
        orders = tuple(self.simulator.orders.values())
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            submitted_quantity = sum(
                (order.original_quantity for order in orders), Decimal("0")
            )
            filled_quantity = sum(
                (fill.quantity for fill in self.simulator.fills), Decimal("0")
            )
            fill_rate = (
                filled_quantity / submitted_quantity
                if submitted_quantity > 0
                else Decimal("0")
            )
            net_pnl = account.net_worth - self.simulator.config.initial_cash
            gross_pnl = net_pnl + account.fees
        return ReplayMetrics(
            snapshots=snapshots,
            applied_deltas=applied,
            stale_deltas=stale,
            public_trades=public_trades,
            warmup_trades=warmup_trades,
            fills=len(self.simulator.fills),
            submitted_orders=len(orders),
            canceled_orders=sum(
                order.status is OrderStatus.CANCELED for order in orders
            ),
            rejected_orders=sum(
                order.status is OrderStatus.REJECTED for order in orders
            ),
            invalidated_orders=sum(
                order.status is OrderStatus.INVALIDATED for order in orders
            ),
            open_orders_at_end=sum(
                order.status in {OrderStatus.PENDING, OrderStatus.ACTIVE}
                for order in orders
            ),
            net_pnl=net_pnl,
            gross_pnl_before_fees=gross_pnl,
            signed_fees=account.fees,
            turnover=account.turnover,
            filled_quantity=filled_quantity,
            submitted_quantity=submitted_quantity,
            quantity_fill_rate=fill_rate,
            maximum_absolute_inventory=self._maximum_absolute_inventory,
            final_account=account,
        )

    def _require_nondecreasing(self, received_time_ns: int) -> None:
        if received_time_ns < self.simulator.current_time_ns:
            raise SchemaError(
                "local receive time regressed after strategy activation; "
                "execution ordering is not trustworthy"
            )


def _mid(book: L2Book) -> Decimal | None:
    if not book.synchronized or book.best_bid is None or book.best_ask is None:
        return None
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        return (book.best_bid + book.best_ask) / Decimal("2")
