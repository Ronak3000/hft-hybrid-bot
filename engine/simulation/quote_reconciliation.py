"""Shared target-quote reconciliation for baseline and learned policies."""

from __future__ import annotations

from engine.market_data import L2Book

from .policies import QuoteTarget
from .queue_simulator import QueueAwareSimulator, Side


def reconcile_quote_target(
    simulator: QueueAwareSimulator,
    book: L2Book,
    target: QuoteTarget,
    received_time_ns: int,
) -> None:
    """Move the simulator toward one desired quote per side.

    Existing orders first enter the configured cancellation path. A replacement
    cannot appear until that order is terminal, so cancel latency remains real.
    """
    desired = {Side.BUY: target.bid_price, Side.SELL: target.ask_price}
    if simulator.inventory >= simulator.config.max_abs_inventory:
        desired[Side.BUY] = None
    if simulator.inventory <= -simulator.config.max_abs_inventory:
        desired[Side.SELL] = None

    for side in Side:
        order = simulator.open_order(side)
        price = desired[side]
        if order is not None:
            if price is None or order.price != price:
                simulator.request_cancel(order.order_id, received_time_ns)
            continue
        if price is not None:
            simulator.submit_limit(side, price, target.quantity, received_time_ns)

    # Zero-latency actions become active after the observation that caused the
    # decision. They can interact only with a later capture record.
    simulator.advance_to(received_time_ns, book)
