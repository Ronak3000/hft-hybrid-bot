from decimal import Decimal
import unittest

from engine.market_data import L2Book, parse_binance_snapshot
from engine.research.alpha_quotes import AlphaWideningPolicy
from engine.simulation.policies import AvellanedaStoikovPolicy


class AlphaQuotesTests(unittest.TestCase):
    def test_matching_update_widens_only_exposed_side_and_reset_clears_it(self):
        d = Decimal
        book = L2Book("binance_spot", "BTCUSDT")
        book.load_snapshot(parse_binance_snapshot({
            "lastUpdateId": 100, "bids": [["99", "1"]], "asks": [["101", "1"]],
        }, "BTCUSDT", 1))
        model = AvellanedaStoikovPolicy(d("0.01"), d("0.001"), d("0.001"), d("0.5"), d("1"), d("60"))
        quotes = AlphaWideningPolicy(model, {(3, 101): 1, (5, 102): -1}, 2)
        for timestamp, key, bid_change, ask_change in (
            (1, None, "0", "0"),
            (2, (2, 101), "0", "0"),  # same ID, but the signal is not available yet
            (3, (3, 101), "0", "0.02"),
            (4, None, "0", "0"),      # snapshot or gap
            (5, (5, 102), "-0.02", "0"),
            (6, (6, 103), "0", "0"),  # no prediction on this update
        ):
            quotes.on_depth(key)
            expected = model.quote(book, d("0"), timestamp)
            actual = quotes.quote(book, d("0"), timestamp)
            self.assertEqual(actual.bid_price - expected.bid_price, d(bid_change))
            self.assertEqual(actual.ask_price - expected.ask_price, d(ask_change))
            self.assertEqual(actual.quantity, expected.quantity)
        self.assertEqual(quotes.matched_updates, 2)
