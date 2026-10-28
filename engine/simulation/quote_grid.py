"""Explicit quote-width choices and a fee-only economic sanity check."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, localcontext
from typing import Any, Sequence

from .queue_simulator import SIMULATION_DECIMAL_CONTEXT, _decimal


def half_spread_choices(
    maximum: int, choices: Sequence[int] | None = None, *, minimum: int = 1
) -> tuple[int, ...]:
    for name, value in (("minimum", minimum), ("maximum", maximum)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} half spread must be a positive integer")
    if minimum > maximum:
        raise ValueError("minimum half spread must not exceed maximum")
    if choices is None:
        return tuple(range(minimum, maximum + 1))
    if isinstance(choices, (str, bytes)):
        raise ValueError("half_spread_tick_choices must be an integer sequence")
    parsed = tuple(choices)
    if not parsed or len(parsed) > 32:
        raise ValueError("half_spread_tick_choices must contain 1 to 32 widths")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        or not minimum <= value <= maximum for value in parsed
    ):
        raise ValueError("half_spread_tick_choices must be integer ticks within bounds")
    if any(left >= right for left, right in zip(parsed, parsed[1:])):
        raise ValueError("half_spread_tick_choices must be strictly increasing")
    return parsed


def quote_grid_economics(
    reference_mid: Decimal | str,
    tick_size: Decimal | str,
    maker_fee_rate: Decimal | str,
    widths: Sequence[int],
) -> dict[str, Any]:
    """Symmetric round-trip arithmetic at one reference mid, not a fill forecast."""
    mid = _decimal(reference_mid, "reference_mid", positive=True)
    tick = _decimal(tick_size, "tick_size", positive=True)
    fee = _decimal(maker_fee_rate, "maker_fee_rate")
    if fee <= -1:
        raise ValueError("maker_fee_rate must exceed -1")
    parsed = tuple(widths)
    # Validate before taking max so empty or non-integer grids fail clearly.
    if not parsed or any(isinstance(w, bool) or not isinstance(w, int) or w <= 0 for w in parsed):
        raise ValueError("widths must contain positive integer ticks")
    if any(left >= right for left, right in zip(parsed, parsed[1:])):
        raise ValueError("widths must be strictly increasing")
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        round_trip_fee = Decimal("2") * fee * mid
        break_even = max(0, int((fee * mid / tick).to_integral_value(rounding=ROUND_CEILING)))
        rows = []
        for width in parsed:
            half_width = tick * width
            edge = Decimal("2") * half_width
            rows.append({
                "half_spread_ticks": width,
                "half_width_quote_currency": str(half_width),
                "round_trip_spread_per_base_unit": str(edge),
                "round_trip_fee_per_base_unit": str(round_trip_fee),
                "fee_only_edge_per_base_unit": str(edge - round_trip_fee),
                "positive_bid_at_reference": mid - half_width > 0,
                "covers_fees_at_reference": edge >= round_trip_fee,
            })
    return {
        "reference_mid": str(mid),
        "tick_size": str(tick),
        "maker_fee_rate": str(fee),
        "fee_only_break_even_half_spread_ticks": break_even,
        "has_fee_covering_valid_width": any(
            row["covers_fees_at_reference"] and row["positive_bid_at_reference"]
            for row in rows
        ),
        "widths": rows,
        "interpretation": (
            "Symmetric same-mid round-trip arithmetic only; assumes both sides fill. "
            "Excludes queue uncertainty, price moves, latency and adverse selection. "
            "Fee coverage does not demonstrate profitability or adequate captured depth."
        ),
    }
