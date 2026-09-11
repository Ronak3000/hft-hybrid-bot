"""Deterministic non-learning market-making baselines."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from typing import Protocol

from engine.market_data import L2Book

from .queue_simulator import SIMULATION_DECIMAL_CONTEXT, _decimal, _nonnegative_int


@dataclass(frozen=True, slots=True)
class QuoteTarget:
    bid_price: Decimal | None
    ask_price: Decimal | None
    quantity: Decimal


class QuotePolicy(Protocol):
    def quote(
        self, book: L2Book, inventory: Decimal, received_time_ns: int
    ) -> QuoteTarget:
        """Return desired passive quotes from information available now."""


@dataclass(frozen=True, slots=True)
class NoQuotePolicy:
    """Explicit zero-activity control with zero market exposure."""

    quantity: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "quantity", _decimal(self.quantity, "quantity", positive=True)
        )

    def quote(
        self, book: L2Book, inventory: Decimal, received_time_ns: int = 0
    ) -> QuoteTarget:
        del book
        del inventory
        del received_time_ns
        return QuoteTarget(None, None, self.quantity)


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

    def quote(
        self, book: L2Book, inventory: Decimal, received_time_ns: int = 0
    ) -> QuoteTarget:
        del inventory
        del received_time_ns
        center = _mid(book)
        if center is None:
            return QuoteTarget(None, None, self.quantity)
        return self._around(center)

    def _around(self, center: Decimal) -> QuoteTarget:
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            half_width = self.tick_size * self.half_spread_ticks
        return quote_target_around(
            center, half_width, self.tick_size, self.quantity
        )


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

    def quote(
        self, book: L2Book, inventory: Decimal, received_time_ns: int = 0
    ) -> QuoteTarget:
        del received_time_ns
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


@dataclass(slots=True)
class SeededRandomPolicy:
    """Cross-version deterministic random-control baseline."""

    tick_size: Decimal
    quantity: Decimal
    seed: int
    minimum_half_spread_ticks: int = 1
    maximum_half_spread_ticks: int = 5
    maximum_absolute_skew_ticks: int = 2
    _state: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.tick_size = _decimal(self.tick_size, "tick_size", positive=True)
        self.quantity = _decimal(self.quantity, "quantity", positive=True)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        for name, value in (
            ("minimum_half_spread_ticks", self.minimum_half_spread_ticks),
            ("maximum_half_spread_ticks", self.maximum_half_spread_ticks),
            ("maximum_absolute_skew_ticks", self.maximum_absolute_skew_ticks),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.minimum_half_spread_ticks <= 0:
            raise ValueError("minimum_half_spread_ticks must be positive")
        if self.minimum_half_spread_ticks > self.maximum_half_spread_ticks:
            raise ValueError("minimum spread must not exceed maximum spread")
        self._state = self.seed & ((1 << 64) - 1)

    def quote(
        self, book: L2Book, inventory: Decimal, received_time_ns: int = 0
    ) -> QuoteTarget:
        del inventory
        del received_time_ns
        center = _mid(book)
        if center is None:
            return QuoteTarget(None, None, self.quantity)
        half_ticks = self._randint(
            self.minimum_half_spread_ticks, self.maximum_half_spread_ticks
        )
        skew_ticks = self._randint(
            -self.maximum_absolute_skew_ticks, self.maximum_absolute_skew_ticks
        )
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            center += self.tick_size * skew_ticks
            half_width = self.tick_size * half_ticks
        return quote_target_around(
            center, half_width, self.tick_size, self.quantity
        )

    def _randint(self, lower: int, upper: int) -> int:
        return lower + self._next_u64() % (upper - lower + 1)

    def _next_u64(self) -> int:
        # SplitMix64 is specified here directly instead of relying on the
        # process-global RNG or a library-version-specific implementation.
        mask = (1 << 64) - 1
        self._state = (self._state + 0x9E3779B97F4A7C15) & mask
        value = self._state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & mask
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & mask
        return (value ^ (value >> 31)) & mask


@dataclass(slots=True)
class AvellanedaStoikovPolicy:
    """Finite-horizon approximation from Avellaneda and Stoikov (2008)."""

    tick_size: Decimal
    quantity: Decimal
    risk_aversion: Decimal
    volatility: Decimal
    intensity_decay: Decimal
    session_horizon_seconds: Decimal
    _start_time_ns: int | None = field(default=None, init=False, repr=False)
    _last_time_ns: int | None = field(default=None, init=False, repr=False)
    _risk_coefficient: Decimal = field(init=False, repr=False)
    _liquidity_spread: Decimal = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.tick_size = _decimal(self.tick_size, "tick_size", positive=True)
        self.quantity = _decimal(self.quantity, "quantity", positive=True)
        self.risk_aversion = _decimal(
            self.risk_aversion, "risk_aversion", positive=True
        )
        self.volatility = _decimal(self.volatility, "volatility", positive=True)
        self.intensity_decay = _decimal(
            self.intensity_decay, "intensity_decay", positive=True
        )
        self.session_horizon_seconds = _decimal(
            self.session_horizon_seconds,
            "session_horizon_seconds",
            positive=True,
        )
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            self._risk_coefficient = (
                self.risk_aversion * self.volatility * self.volatility
            )
            self._liquidity_spread = (
                Decimal("2")
                / self.risk_aversion
                * (Decimal("1") + self.risk_aversion / self.intensity_decay).ln()
            )

    def quote(
        self, book: L2Book, inventory: Decimal, received_time_ns: int = 0
    ) -> QuoteTarget:
        timestamp = _nonnegative_int(received_time_ns, "received_time_ns")
        center = _mid(book)
        if center is None:
            return QuoteTarget(None, None, self.quantity)
        if self._start_time_ns is None:
            self._start_time_ns = timestamp
        if self._last_time_ns is not None and timestamp < self._last_time_ns:
            raise ValueError("Avellaneda-Stoikov policy time must be nondecreasing")
        self._last_time_ns = timestamp
        parsed_inventory = _decimal(inventory, "inventory")
        with localcontext(SIMULATION_DECIMAL_CONTEXT):
            elapsed = Decimal(timestamp - self._start_time_ns) / Decimal("1000000000")
            remaining = max(self.session_horizon_seconds - elapsed, Decimal("0"))
            risk_term = self._risk_coefficient * remaining
            reservation_price = center - parsed_inventory * risk_term
            total_spread = risk_term + self._liquidity_spread
            half_width = total_spread / Decimal("2")
        return quote_target_around(
            reservation_price, half_width, self.tick_size, self.quantity
        )


def _mid(book: L2Book) -> Decimal | None:
    if not book.synchronized or book.best_bid is None or book.best_ask is None:
        return None
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        return (book.best_bid + book.best_ask) / Decimal("2")


def _round_to_tick(price: Decimal, tick: Decimal, rounding: str) -> Decimal:
    units = (price / tick).to_integral_value(rounding=rounding)
    return units * tick


def quote_target_around(
    center: Decimal, half_width: Decimal, tick: Decimal, quantity: Decimal
) -> QuoteTarget:
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        bid = _round_to_tick(center - half_width, tick, ROUND_FLOOR)
        ask = _round_to_tick(center + half_width, tick, ROUND_CEILING)
    if bid <= 0 or bid >= ask:
        return QuoteTarget(None, None, quantity)
    return QuoteTarget(bid, ask, quantity)
