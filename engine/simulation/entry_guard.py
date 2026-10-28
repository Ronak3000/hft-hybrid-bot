"""Optional current-mid entry-cost veto, not an alpha or profit forecast."""

from decimal import Decimal, localcontext

from .policies import QuoteTarget
from .queue_simulator import SIMULATION_DECIMAL_CONTEXT


def guard_entry_costs(
    target: QuoteTarget, mid: Decimal, inventory: Decimal,
    fee_rate: Decimal, buffer_bps: Decimal,
) -> QuoteTarget:
    """Veto fee-deficient exposure additions, while permitting reductions.

    A permitted fill can still lose after price moves, exit costs and latency.
    This uses the current observable mid, never a future price or fill outcome.
    If a fee-deficient quote reduces inventory, cap its requested size so it
    cannot deliberately open an opposite position in the same request.
    """
    with localcontext(SIMULATION_DECIMAL_CONTEXT):
        reserve = mid * buffer_bps / Decimal("10000")
        bid, ask, quantity = target.bid_price, target.ask_price, target.quantity
        if bid is not None and mid - bid * (1 + fee_rate) < reserve:
            if inventory < 0:
                quantity = min(quantity, -inventory)
            else:
                bid = None
        if ask is not None and ask * (1 - fee_rate) - mid < reserve:
            if inventory > 0:
                quantity = min(quantity, inventory)
            else:
                ask = None
        return QuoteTarget(bid, ask, quantity)
