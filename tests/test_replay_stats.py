import unittest
from engine.research.replay_stats import ReplayStats


class ReplayStatsTests(unittest.TestCase):
    def test_partial_close_and_reversal_with_fees(self):
        s=ReplayStats()
        s.fill("buy",100,2,2)
        self.assertEqual(s.mark(0)["closed"],0)
        s.fill("sell",102,1,1)
        self.assertEqual((s.closed,s.wins),(1,0))  # break-even after fees
        s.fill("sell",104,2,2)
        s.fill("buy",100,1)
        self.assertEqual((s.closed,s.wins,s.buys,s.sells),(3,2,2,2))

    def test_drawdown_includes_initial_zero_and_intrabucket_loss(self):
        s=ReplayStats()
        for p in [-1,3,-2,4]:
            result=s.mark(p)
        self.assertEqual(result["drawdown_usdt"],5)
