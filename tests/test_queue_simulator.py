from __future__ import annotations

import unittest
from decimal import Decimal, localcontext

from engine.market_data import (
    L2Book,
    MarketTrade,
    parse_binance_delta,
    parse_binance_snapshot,
)
from engine.simulation import OrderStatus, QueueAwareSimulator, Side, SimulationConfig


def _book() -> L2Book:
    book = L2Book("binance_spot", "BTCUSDT")
    book.load_snapshot(
        parse_binance_snapshot(
            {
                "lastUpdateId": 100,
                "bids": [["100", "5"], ["99", "8"]],
                "asks": [["102", "7"], ["103", "9"]],
            },
            "BTCUSDT",
            1,
        )
    )
    return book


def _trade(
    trade_id: int,
    price: str,
    quantity: str,
    received_time_ns: int,
    *,
    aggressor: str,
) -> MarketTrade:
    return MarketTrade(
        venue="binance_spot",
        symbol="BTCUSDT",
        received_time_ns=received_time_ns,
        event_time_ms=received_time_ns // 1_000_000,
        trade_time_ms=received_time_ns // 1_000_000,
        trade_id=trade_id,
        price=Decimal(price),
        quantity=Decimal(quantity),
        buyer_is_maker=aggressor == "sell",
    )


class QueueAwareFillTests(unittest.TestCase):
    def test_latency_and_queue_ahead_prevent_immediate_fill(self) -> None:
        book = _book()
        simulator = QueueAwareSimulator(
            SimulationConfig(
                initial_cash=Decimal("1000"),
                maker_fee_rate=Decimal("0.001"),
                order_latency_ns=10,
            )
        )
        order_id = simulator.submit_limit(Side.BUY, "100", "2", 0)

        self.assertEqual(
            simulator.process_trade(_trade(1, "100", "10", 5, aggressor="sell"), book),
            (),
        )
        first = simulator.process_trade(
            _trade(2, "100", "4", 10, aggressor="sell"), book
        )
        self.assertEqual(first, ())
        self.assertEqual(simulator.orders[order_id].queue_ahead, Decimal("1"))

        fills = simulator.process_trade(
            _trade(3, "100", "2", 11, aggressor="sell"), book
        )
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].quantity, Decimal("1"))
        self.assertEqual(simulator.orders[order_id].remaining_quantity, Decimal("1"))
        self.assertEqual(simulator.inventory, Decimal("1"))
        self.assertEqual(simulator.cash, Decimal("899.900"))

    def test_wrong_aggressor_does_not_fill_and_trade_through_does(self) -> None:
        book = _book()
        simulator = QueueAwareSimulator()
        order_id = simulator.submit_limit("buy", "100", "2", 0)
        simulator.advance_to(0, book)

        self.assertEqual(
            simulator.process_trade(_trade(1, "100", "20", 1, aggressor="buy"), book),
            (),
        )
        fills = simulator.process_trade(
            _trade(2, "99", "0.01", 2, aggressor="sell"), book
        )
        self.assertEqual(fills[0].quantity, Decimal("2"))
        self.assertEqual(fills[0].price, Decimal("100"))
        self.assertEqual(simulator.orders[order_id].status, OrderStatus.FILLED)

    def test_sell_fill_fee_and_accounting_identity(self) -> None:
        book = _book()
        simulator = QueueAwareSimulator(
            SimulationConfig(
                initial_cash=Decimal("1000"), maker_fee_rate=Decimal("-0.001")
            )
        )
        simulator.submit_limit("sell", "101", "2", 0)
        simulator.advance_to(0, book)
        fills = simulator.process_trade(
            _trade(1, "101", "2", 1, aggressor="buy"), book
        )

        self.assertEqual(fills[0].notional, Decimal("202"))
        self.assertEqual(fills[0].fee, Decimal("-0.202"))
        self.assertEqual(simulator.cash, Decimal("1202.202"))
        self.assertEqual(simulator.inventory, Decimal("-2"))
        account = simulator.account("101")
        self.assertEqual(account.net_worth, Decimal("1000.202"))
        self.assertEqual(account.turnover, Decimal("202"))
        self.assertEqual(account.fees, Decimal("-0.202"))

    def test_global_decimal_precision_cannot_change_accounting(self) -> None:
        def run(precision: int) -> tuple[Decimal, Decimal, Decimal]:
            book = _book()
            simulator = QueueAwareSimulator(
                SimulationConfig(
                    initial_cash=Decimal("1000"),
                    maker_fee_rate=Decimal("0.000123456789"),
                )
            )
            with localcontext() as context:
                context.prec = precision
                simulator.submit_limit("buy", "101.123456789", "0.123456789", 0)
                simulator.advance_to(0, book)
                simulator.process_trade(
                    _trade(1, "100", "1", 1, aggressor="sell"), book
                )
                account = simulator.account("101.5")
            return account.cash, account.fees, account.net_worth

        self.assertEqual(run(6), run(28))

    def test_inventory_limit_caps_a_fill(self) -> None:
        book = _book()
        simulator = QueueAwareSimulator(
            SimulationConfig(max_abs_inventory=Decimal("0.5"))
        )
        order_id = simulator.submit_limit("buy", "101", "2", 0)
        simulator.advance_to(0, book)
        fills = simulator.process_trade(
            _trade(1, "101", "2", 1, aggressor="sell"), book
        )
        self.assertEqual(fills[0].quantity, Decimal("0.5"))
        self.assertEqual(simulator.inventory, Decimal("0.5"))
        self.assertEqual(simulator.orders[order_id].remaining_quantity, Decimal("1.5"))

    def test_displayed_cancellation_gets_no_queue_credit(self) -> None:
        book = _book()
        simulator = QueueAwareSimulator()
        order_id = simulator.submit_limit("buy", "100", "1", 0)
        simulator.advance_to(0, book)
        book.apply_delta(
            parse_binance_delta(
                {
                    "e": "depthUpdate",
                    "E": 1,
                    "s": "BTCUSDT",
                    "U": 101,
                    "u": 101,
                    "b": [["100", "0"]],
                    "a": [],
                },
                1,
            )
        )
        self.assertEqual(simulator.orders[order_id].queue_ahead, Decimal("5"))
        self.assertEqual(
            simulator.process_trade(_trade(1, "100", "5", 1, aggressor="sell"), book),
            (),
        )


class QuoteLifecycleTests(unittest.TestCase):
    def test_cancel_latency_allows_fill_before_cancel_arrives(self) -> None:
        book = _book()
        simulator = QueueAwareSimulator(SimulationConfig(cancel_latency_ns=5))
        order_id = simulator.submit_limit("buy", "101", "1", 0)
        simulator.advance_to(0, book)
        self.assertTrue(simulator.request_cancel(order_id, 10))

        fills = simulator.process_trade(
            _trade(1, "100", "0.1", 14, aggressor="sell"), book
        )
        self.assertEqual(len(fills), 1)
        self.assertEqual(simulator.orders[order_id].status, OrderStatus.FILLED)

    def test_cancel_before_activation_prevents_quote(self) -> None:
        book = _book()
        simulator = QueueAwareSimulator(
            SimulationConfig(order_latency_ns=10, cancel_latency_ns=2)
        )
        order_id = simulator.submit_limit("sell", "102", "1", 0)
        self.assertTrue(simulator.request_cancel(order_id, 1))
        simulator.advance_to(10, book)
        self.assertEqual(simulator.orders[order_id].status, OrderStatus.CANCELED)

    def test_cancel_cannot_precede_submission_decision(self) -> None:
        simulator = QueueAwareSimulator()
        order_id = simulator.submit_limit("buy", "100", "1", 10)
        with self.assertRaises(ValueError):
            simulator.request_cancel(order_id, 9)

    def test_marketable_quote_is_rejected_at_activation(self) -> None:
        book = _book()
        simulator = QueueAwareSimulator()
        order_id = simulator.submit_limit("buy", "102", "1", 0)
        simulator.advance_to(0, book)
        order = simulator.orders[order_id]
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertEqual(order.rejection_reason, "would_take_liquidity")

    def test_gap_immediately_invalidates_pending_and_active_quotes(self) -> None:
        book = _book()
        simulator = QueueAwareSimulator(SimulationConfig(order_latency_ns=10))
        buy_id = simulator.submit_limit("buy", "100", "1", 0)
        sell_id = simulator.submit_limit("sell", "102", "1", 0)
        simulator.advance_to(5, book)
        self.assertEqual(simulator.invalidate_open_orders(6), 2)
        simulator.advance_to(20, book)
        self.assertEqual(simulator.orders[buy_id].status, OrderStatus.INVALIDATED)
        self.assertEqual(simulator.orders[sell_id].status, OrderStatus.INVALIDATED)

    def test_one_open_quote_per_side_and_time_ordering_are_enforced(self) -> None:
        simulator = QueueAwareSimulator()
        simulator.submit_limit("buy", "100", "1", 0)
        with self.assertRaises(ValueError):
            simulator.submit_limit("buy", "99", "1", 0)
        with self.assertRaises(ValueError):
            simulator.submit_limit("sell", "102", "1", -1)

    def test_terminal_order_releases_constant_time_side_slot(self) -> None:
        book = _book()
        simulator = QueueAwareSimulator()
        first_id = simulator.submit_limit("buy", "101", "1", 0)
        simulator.advance_to(0, book)
        simulator.process_trade(_trade(1, "100", "1", 1, aggressor="sell"), book)
        self.assertEqual(simulator.orders[first_id].status, OrderStatus.FILLED)
        second_id = simulator.submit_limit("buy", "100", "1", 1)
        self.assertNotEqual(first_id, second_id)

    def test_configuration_rejects_invalid_costs_and_latency(self) -> None:
        with self.assertRaises(ValueError):
            SimulationConfig(maker_fee_rate=Decimal("-1"))
        with self.assertRaises(ValueError):
            SimulationConfig(order_latency_ns=-1)
        with self.assertRaises(ValueError):
            SimulationConfig(order_latency_ns=1.5)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            SimulationConfig(max_abs_inventory=Decimal("0"))
        with self.assertRaises(ValueError):
            SimulationConfig(initial_cash=Decimal("-1"))


if __name__ == "__main__":
    unittest.main()
