"""Bounded, causal observation extensions; never used for cash accounting."""

from __future__ import annotations

import math
from decimal import Decimal
from heapq import nlargest, nsmallest

from engine.market_data import L2Book, MarketTrade
from engine.simulation import QueueAwareSimulator, Side


MARKET_FEATURE_NAMES = (
    "spread_bps_div10", "microprice_offset_bps", "step_return_bps_div10",
    "fast_momentum_bps_div10", "slow_momentum_bps_div10",
    "volatility_bps_per_sqrt_second_div10", "aggressive_volume_imbalance",
    "log_trade_volume_div20", "top5_depth_imbalance",
    "bid_distance_bps_div100", "ask_distance_bps_div100", "elapsed_seconds_div10",
)


class CausalMarketFeatures:
    """5s/30s time-aware price EMAs and trades since the last observation.

    Everything is reset at a capture/sequence boundary. No future returns,
    fitted normalization, or training labels enter these features.
    """

    def __init__(self) -> None:
        self.previous_mid: Decimal | None = None
        self.previous_time_ns: int | None = None
        self.fast_price = 0.0
        self.slow_price = 0.0
        self.variance_rate = 0.0
        self.buy_volume = Decimal("0")
        self.sell_volume = Decimal("0")

    def trade(self, trade: MarketTrade) -> None:
        if trade.aggressor_side == "buy":
            self.buy_volume += trade.quantity
        else:
            self.sell_volume += trade.quantity

    def observe(
        self, book: L2Book, simulator: QueueAwareSimulator, mid: Decimal,
        microprice: Decimal, quantity: Decimal, time_ns: int,
    ) -> tuple[float, ...]:
        price = float(mid)
        elapsed = 0.0 if self.previous_time_ns is None else max(0.0, (time_ns - self.previous_time_ns) / 1e9)
        if self.previous_mid is None:
            step_return = 0.0
            self.fast_price = self.slow_price = price
        else:
            step_return = float((mid / self.previous_mid - 1) * 10000)
            fast_weight = -math.expm1(-elapsed / 5.0)
            slow_weight = -math.expm1(-elapsed / 30.0)
            self.fast_price += fast_weight * (price - self.fast_price)
            self.slow_price += slow_weight * (price - self.slow_price)
            if elapsed > 0:
                rate = step_return * step_return / max(elapsed, 1e-3)
                self.variance_rate += fast_weight * (rate - self.variance_rate)
        bid_depth = sum((book.bids[p] for p in nlargest(5, book.bids)), Decimal("0"))
        ask_depth = sum((book.asks[p] for p in nsmallest(5, book.asks)), Decimal("0"))
        volume = self.buy_volume + self.sell_volume
        bid = simulator.open_order(Side.BUY)
        ask = simulator.open_order(Side.SELL)
        values = (
            float((book.best_ask - book.best_bid) / mid * 10000) / 10,
            float((microprice - mid) / mid * 10000),
            step_return / 10,
            (price - self.fast_price) / price * 10000 / 10,
            (price - self.slow_price) / price * 10000 / 10,
            math.sqrt(max(0.0, self.variance_rate)) / 10,
            float((self.buy_volume - self.sell_volume) / volume) if volume else 0.0,
            math.log1p(float(volume / quantity)) / 20,
            float((bid_depth - ask_depth) / (bid_depth + ask_depth)),
            float((mid - bid.price) / mid * 10000) / 100 if bid else 0.0,
            float((ask.price - mid) / mid * 10000) / 100 if ask else 0.0,
            elapsed / 10,
        )
        self.previous_mid = mid
        self.previous_time_ns = time_ns
        self.buy_volume = self.sell_volume = Decimal("0")
        return tuple(max(-1.0, min(1.0, value)) for value in values)
