from __future__ import annotations

import unittest
from decimal import Decimal, localcontext

from engine.simulation.quote_grid import half_spread_choices, quote_grid_economics


class QuoteGridTests(unittest.TestCase):
    def test_default_and_sparse_widths_have_distinct_cardinality_and_range(self):
        self.assertEqual(half_spread_choices(5), (1, 2, 3, 4, 5))
        self.assertEqual(half_spread_choices(10000, (1, 100, 6000, 10000)), (1, 100, 6000, 10000))
        for choices in ((), (2, 1), (1, 1), (0, 1), (1, 101), (True,), (1.5,), "12", tuple(range(1, 34))):
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                half_spread_choices(100, choices)

    def test_old_pilot_widths_do_not_cover_fee_only_round_trip(self):
        report = quote_grid_economics("60000", "0.01", "0.001", (1, 5))
        self.assertEqual(report["fee_only_break_even_half_spread_ticks"], 6000)
        self.assertFalse(report["has_fee_covering_valid_width"])
        self.assertEqual(Decimal(report["widths"][1]["fee_only_edge_per_base_unit"]), Decimal("-119.90"))

    def test_fee_coverage_is_rounded_up_and_does_not_imply_positive_edge(self):
        report = quote_grid_economics("60000.01", "0.01", "0.001", (6000, 6001))
        self.assertEqual(report["fee_only_break_even_half_spread_ticks"], 6001)
        self.assertFalse(report["widths"][0]["covers_fees_at_reference"])
        self.assertTrue(report["widths"][1]["covers_fees_at_reference"])
        exact = quote_grid_economics("60000", "0.01", "0.001", (6000,))
        self.assertEqual(Decimal(exact["widths"][0]["fee_only_edge_per_base_unit"]), Decimal("0"))

    def test_zero_fee_and_rebate_remain_explicit(self):
        for fee in ("0", "-0.0001"):
            report = quote_grid_economics("60000", "0.01", fee, (1,))
            self.assertEqual(report["fee_only_break_even_half_spread_ticks"], 0)
            self.assertTrue(report["has_fee_covering_valid_width"])
        impossible = quote_grid_economics("100", "1", "1", (100,))
        self.assertFalse(impossible["has_fee_covering_valid_width"])

    def test_global_decimal_precision_and_invalid_inputs(self):
        with localcontext() as context:
            context.prec = 4
            first = quote_grid_economics("60000.123456", "0.01", "0.001", (6000, 6001))
        second = quote_grid_economics("60000.123456", "0.01", "0.001", (6000, 6001))
        self.assertEqual(first, second)
        for mid, tick, fee in (("NaN", "1", "0"), ("1", "0", "0"), ("1", "1", "Infinity"), ("1", "1", "-1")):
            with self.assertRaises(ValueError):
                quote_grid_economics(mid, tick, fee, (1,))
        for widths in ((), (1, 1), (2, 1), (True,), (1.0,)):
            with self.assertRaises(ValueError):
                quote_grid_economics("100", "1", "0", widths)


if __name__ == "__main__":
    unittest.main()
