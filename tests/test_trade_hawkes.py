import importlib.util
import math
from pathlib import Path
import unittest


@unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy is optional")
class TradeHawkesTests(unittest.TestCase):
    def test_equal_time_trades_do_not_excite_each_other(self):
        from engine.research.trade_hawkes import Arrivals, sufficient_statistics

        trades = ((0, 0), (1_000_000_000, 0), (1_000_000_000, 1), (2_000_000_000, 1))
        session = Arrivals(Path("fixture"), "hash", ("binance_spot", "BTCUSDT"), trades)
        x, y, basis = sufficient_statistics(session, 1)
        self.assertEqual(y.tolist(), [[1, 1], [0, 1]])
        self.assertEqual(x[0, 2], 0)
        self.assertAlmostEqual(x[0, 1], math.exp(-1))
        self.assertAlmostEqual(x[1, 2], math.exp(-1))
        self.assertAlmostEqual(basis[1], 2 - math.exp(-1) - math.exp(-2))
        self.assertAlmostEqual(basis[2], 1 - math.exp(-1))
