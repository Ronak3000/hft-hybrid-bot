"""Historical paper-fill accounting, independent of chart display resolution."""
from collections import deque
from decimal import Decimal


class ReplayStats:
    def __init__(self):
        self.lots = deque()
        self.wins = self.closed = self.buys = self.sells = 0
        self.peak = self.drawdown = Decimal(0)

    def fill(self, side, price, qty, fee=0):
        p, q, f = (Decimal(str(x)) for x in (price, qty, fee))
        sign = 1 if side == "buy" else -1
        self.buys += int(sign == 1)
        self.sells += int(sign == -1)
        # Effective entry/exit prices allocate fees proportionally to quantity.
        p += sign * f/q
        realized = Decimal(0)
        matched = False
        while q and self.lots and self.lots[0][0] != sign:
            s, old, remaining = self.lots[0]
            n = min(q, remaining)
            realized += (p-old)*s*n
            matched = True
            q -= n
            if n == remaining:
                self.lots.popleft()
            else:
                self.lots[0] = (s,old,remaining-n)
        if matched:
            self.closed += 1
            self.wins += int(realized > 0)
        if q:
            self.lots.append((sign,p,q))

    def mark(self, pnl):
        value = Decimal(str(pnl))
        self.peak = max(self.peak,value)
        self.drawdown = max(self.drawdown,self.peak-value)
        return dict(buys=self.buys,sells=self.sells,closed=self.closed,wins=self.wins,
                    drawdown_usdt=float(self.drawdown))
