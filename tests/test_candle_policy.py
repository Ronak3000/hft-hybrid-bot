import unittest
from unittest.mock import MagicMock, patch
from engine.market_data.candles import get_bars
from engine.rl_trading.candle_policy import CandleEnv, next_live_bars, split_sessions


class CandleTests(unittest.TestCase):
    def test_gap_is_not_a_price_move_or_fill(self):
        rows=[[i*60000,p,p,p,p,1] for i,p in [(0,1),(1,2),(10,900),(11,901)]]
        env=CandleEnv(rows,split_sessions(rows))
        env.reset()
        _,reward,done,_,_=env.step(1)
        self.assertTrue(done)
        self.assertEqual(reward,0)
        env.reset()
        self.assertEqual((env.rows[0][1],env.position,env.pnl),(900,0,0))
        with self.assertRaisesRegex(ValueError,"gap"):
            env.advance(rows[1],rows[2],1)
    def test_action_does_not_earn_move_before_execution(self):
        env = CandleEnv([[i*60000,p,p,p,p,1] for i,p in enumerate([100,200,210])])
        env.reset()
        self.assertEqual(env.step(1)[1],0)
        self.assertAlmostEqual(env.step(0)[1],.01)
        self.assertEqual(env.result()["inventory_btc"],0)

    def test_missing_minute_rejected(self):
        response = MagicMock()
        response.json.return_value = [[60000,1,1,1,1,0,119999]]
        with patch("engine.market_data.candles.requests.Session") as session:
            session.return_value.__enter__.return_value.get.return_value = response
            with self.assertRaisesRegex(ValueError,"discontinuous"):
                get_bars("BTCUSDT",0,120000)

    def test_live_waits_for_late_tail_without_crossing_an_observed_gap(self):
        with patch("engine.rl_trading.candle_policy.get_bars", return_value=[]) as fetch:
            self.assertEqual(next_live_bars("BTCUSDT", 0, 60000, lambda: None), [])
            with self.assertRaisesRegex(ValueError, "stale"):
                next_live_bars("BTCUSDT", 0, 120000, lambda: None)
            fetch.return_value = [[60000, 1, 1, 1, 1, 1]]
            with self.assertRaisesRegex(ValueError, "gap"):
                next_live_bars("BTCUSDT", 0, 120000, lambda: None)
