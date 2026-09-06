"""Deterministic non-learning market-making baselines."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from typing import Protocol

from engine.market_data import L2Book

from .queue_simulator import SIMULATION_DECIMAL_CONTEXT, _decimal


@dataclass(frozen=True, slots=True)
class QuoteTarget:
    bid_price: Decimal | None
    ask_price: Decimal | None
    quantity: Decimal


class QuotePolicy(Protocol):
    def quote(self, book: L2Book, inventory: Decimal) -> QuoteTarget:
        """Return desired passive quotes from information available now."""


@dataclass(frozen=True, slots=True)
class FixedSpreadPolicy:
    tick_size: Decimal
    quantity: Decimal
    half_spread_ticks: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tick_size", _decimal(self.tick_size, "tick_size", positive=True)
        )
        object.__setattr__(
            self, "quantity", _decimal(self.quantity, "quantity", positive=True)
        )
        if (
            isinstance(self.half_spread_ticks, bool)
            or not isinstance(self.half_spread_ticks, int)
            or self.half_spread_ticks <= 0
        ):
            raise ValueError("half_spread_ticks must be a positive integer")

    def quote(self, book: L2Book, inventory: Decimal) -> QuoteTarget:
        del inventory
        center = _mid(book)
        if center is None:
            return QuoteTarget(None, None, self.quantity)
        return self._around(center)

    def _around(self, center: Decimal) -> QuoteTarget:
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            half_width = self.tick_size * self.half_spread_ticks
            bid = _round_to_tick(center - half_width, self.tick_size, ROUND_FLOOR)
            ask = _round_to_tick(center + half_width, self.tick_size, ROUND_CEILING)
        if bid <= 0 or bid >= ask:
            return QuoteTarget(None, None, self.quantity)
        return QuoteTarget(bid, ask, self.quantity)


@dataclass(frozen=True, slots=True)
class InventorySkewPolicy(FixedSpreadPolicy):
    max_abs_inventory: Decimal = Decimal("10")
    max_skew_ticks: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        super(InventorySkewPolicy, self).__post_init__()
        object.__setattr__(
            self,
            "max_abs_inventory",
            _decimal(self.max_abs_inventory, "max_abs_inventory", positive=True),
        )
        max_skew = _decimal(self.max_skew_ticks, "max_skew_ticks")
        if max_skew < 0:
            raise ValueError("max_skew_ticks must be non-negative")
        object.__setattr__(self, "max_skew_ticks", max_skew)

    def quote(self, book: L2Book, inventory: Decimal) -> QuoteTarget:
        center = _mid(book)
        if center is None:
            return QuoteTarget(None, None, self.quantity)
        parsed_inventory = _decimal(inventory, "inventory")
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            ratio = max(
                Decimal("-1"),
                min(Decimal("1"), parsed_inventory / self.max_abs_inventory),
            )
            # Positive inventory lowers both quotes to discourage more buying
            # and encourage inventory-reducing sells. Negative inventory does
            # the symmetric operation.
            skew = ratio * self.max_skew_ticks * self.tick_size
            adjusted_center = center - skew
        return self._around(adjusted_center)


def _mid(book: L2Book) -> Decimal | None:
    if not book.synchronized or book.best_bid is None or book.best_ask is None:
        return None
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        return (book.best_bid + book.best_ask) / Decimal("2")


def _round_to_tick(price: Decimal, tick: Decimal, rounding: str) -> Decimal:
    units = (price / tick).to_integral_value(rounding=rounding)
    return units * tick
