"""Bounded display buckets; each price comes from an observed bar or book mid."""
class TraderTrace:
    def __init__(self, seconds=60, source="Binance.US 1m OHLCV"):
        self.seconds = max(1, int(seconds))
        self.source = source
        self.points = []

    def add(self, timestamp, o,h,l,c, pnl, inventory, fills):
        t = int(timestamp)//self.seconds*self.seconds
        p = dict(time=t,open=float(o),high=float(h),low=float(l),close=float(c),
                 pnl=float(pnl),inventory=float(inventory),fills=int(fills))
        if self.points and self.points[-1]["time"] == t:
            old = self.points[-1]
            p.update(open=old["open"],high=max(old["high"],p["high"]),low=min(old["low"],p["low"]))
            self.points[-1] = p
        else:
            self.points.append(p)

    def payload(self):
        return {"chart": self.points, "chart_source": self.source, "bucket_seconds":self.seconds}
