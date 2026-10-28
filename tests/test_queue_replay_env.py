from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from engine.market_data import CaptureWriter

try:
    import gymnasium
    import numpy as np
    from gymnasium.utils.env_checker import check_env

    from engine.rl_trading.envs import QueueReplayEnv
    from engine.simulation import FixedSpreadPolicy, SimulationConfig
except ModuleNotFoundError:
    gymnasium = None


def _snapshot() -> dict:
    return {
        "lastUpdateId": 100,
        "bids": [["100", "5"]],
        "asks": [["102", "5"]],
    }


def _delta(update_id: int, received: int, bids=None, asks=None) -> dict:
    return {
        "e": "depthUpdate",
        "E": received // 1_000_000,
        "s": "BTCUSDT",
        "U": update_id,
        "u": update_id,
        "b": bids or [],
        "a": asks or [],
    }


def _trade(trade_id: int, received: int) -> dict:
    return {
        "e": "trade",
        "E": received // 1_000_000,
        "s": "BTCUSDT",
        "t": trade_id,
        "p": "101",
        "q": "6",
        "T": received // 1_000_000,
        "m": True,
    }


def _capture(path: Path, *, gap: bool = False, time_offset: int = 0) -> None:
    metadata = {"venue": "binance_spot", "symbol": "BTCUSDT"}
    with CaptureWriter(path, metadata) as writer:
        writer.write("snapshot", _snapshot(), time_offset + 10)
        writer.write(
            "delta",
            _delta(101, time_offset + 5, bids=[["101", "5"]]),
            time_offset + 5,
        )
        writer.write(
            "delta", _delta(102, time_offset + 12), time_offset + 12
        )
        if gap:
            writer.write(
                "trade_gap",
                {"after_trade_id": 1, "before_trade_id": 3},
                time_offset + 13,
            )
        else:
            writer.write(
                "trade", _trade(1, time_offset + 13), time_offset + 13
            )
            writer.write(
                "delta",
                _delta(
                    103,
                    time_offset + 15,
                    bids=[["101", "0"], ["100", "5"]],
                ),
                time_offset + 15,
            )


def _multisegment_capture(path: Path) -> None:
    metadata = {"venue": "binance_spot", "symbol": "BTCUSDT"}
    with CaptureWriter(path, metadata) as writer:
        writer.write("snapshot", _snapshot(), 10)
        writer.write("delta", _delta(101, 11), 11)
        writer.write("disconnect", {"reason": "test"}, 12)
        writer.write("snapshot", {**_snapshot(), "lastUpdateId": 200}, 100)
        writer.write("delta", _delta(201, 101), 101)
        writer.write("delta", _delta(202, 102), 102)


@unittest.skipIf(gymnasium is None, "gymnasium is not installed")
class QueueReplayEnvTests(unittest.TestCase):
    def test_entry_guard_fee_math_and_capped_inventory_reduction(self):
        from engine.simulation import QuoteTarget
        from engine.simulation.entry_guard import guard_entry_costs
        D = Decimal
        narrow = QuoteTarget(D("100.5"), D("101.5"), D("1"))
        flat = guard_entry_costs(narrow, D("101"), D("0"), D("0.01"), D("0"))
        self.assertIsNone(flat.bid_price)
        self.assertIsNone(flat.ask_price)
        long = guard_entry_costs(narrow, D("101"), D("0.2"), D("0.01"), D("0"))
        self.assertIsNone(long.bid_price)
        self.assertEqual(long.ask_price, narrow.ask_price)
        self.assertEqual(long.quantity, D("0.2"))
        short = guard_entry_costs(narrow, D("101"), D("-0.3"), D("0.01"), D("0"))
        self.assertIsNone(short.ask_price)
        self.assertEqual(short.quantity, D("0.3"))
        wide = QuoteTarget(D("99"), D("103"), D("1"))
        self.assertEqual(guard_entry_costs(wide, D("101"), D("0"), D("0.01"), D("0")), wide)
        buffered = guard_entry_costs(wide, D("101"), D("0"), D("0.01"), D("101"))
        self.assertIsNone(buffered.bid_price)
        self.assertIsNone(buffered.ask_price)

    def test_guard_vetoes_before_fill_not_by_removing_fills(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            for guard, expected_fills in ((None, 1), ("0", 0)):
                env = QueueReplayEnv((path,), tick_size="0.5", quantity="1",
                    maximum_half_spread_ticks=2, maximum_absolute_skew_ticks=1,
                    simulation_config=SimulationConfig(initial_cash=Decimal("1000"), maker_fee_rate=Decimal("0.01")),
                    entry_fee_buffer_bps=guard, record_fill_diagnostics=True)
                try:
                    env.reset()
                    env.step(2)
                    _, _, _, _, info = env.step(2)
                    self.assertEqual(info["total_fills"], expected_fills)
                    self.assertEqual(len(env.fill_diagnostics), expected_fills)
                    if expected_fills:
                        fill = env.fill_diagnostics[0]
                        self.assertEqual(Decimal(fill["mid_at_fill"]), Decimal("101.5"))
                        self.assertEqual(Decimal(fill["spread_capture"]), Decimal("0.5"))
                        self.assertLess(Decimal(fill["instant_edge_after_fee"]), 0)
                    else:
                        self.assertEqual(info["submitted_orders"], 0)
                        self.assertEqual(Decimal(info["fees"]), 0)
                finally:
                    env.close()

    def test_smaller_target_quantity_cancels_existing_order_before_replacement(self):
        from engine.simulation import QuoteTarget, Side, OrderStatus
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            env = self._environment(path)
            try:
                env.reset()
                env.step(2)
                order_id = env.simulator.open_order(Side.BUY).order_id
                env.step_quote_target(QuoteTarget(Decimal("101"), None, Decimal("0.25")))
                self.assertEqual(env.simulator.orders[order_id].status, OrderStatus.CANCELED)
                self.assertLessEqual(env.simulator.open_order(Side.BUY).remaining_quantity, Decimal("0.25"))
            finally:
                env.close()

    def test_resize_does_not_erase_fills_during_cancel_latency(self):
        from engine.simulation import QuoteTarget, Side
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            env = QueueReplayEnv((path,), tick_size="0.5", quantity="1",
                maximum_half_spread_ticks=2, maximum_absolute_skew_ticks=1,
                simulation_config=SimulationConfig(cancel_latency_ns=10))
            try:
                env.reset()
                env.step(2)
                order_id = env.simulator.open_order(Side.BUY).order_id
                _, _, _, _, info = env.step_quote_target(QuoteTarget(Decimal("101"), None, Decimal("0.25")))
                self.assertEqual(env.simulator.orders[order_id].cancel_effective_time_ns, 22)
                self.assertEqual(info["total_fills"], 1)
                self.assertEqual(env.simulator.fills[0].quantity, Decimal("1"))
            finally:
                env.close()

    def _environment(self, path: Path) -> "QueueReplayEnv":
        return QueueReplayEnv(
            (path,),
            tick_size=Decimal("0.5"),
            quantity=Decimal("1"),
            simulation_config=SimulationConfig(
                initial_cash=Decimal("1000"),
                max_abs_inventory=Decimal("10"),
            ),
            maximum_half_spread_ticks=2,
            maximum_absolute_skew_ticks=1,
        )

    def test_causal_reset_action_mapping_and_queue_fill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            env = self._environment(path)
            observation, reset_info = env.reset(seed=7)

            self.assertTrue(env.observation_space.contains(observation))
            self.assertEqual(reset_info["decision_time_ns"], 10)
            self.assertEqual(
                env.action_parameters(2),
                {"quote": True, "half_spread_ticks": 1, "skew_ticks": 0},
            )

            first_observation, first_reward, terminated, truncated, first_info = (
                env.step(2)
            )
            self.assertTrue(env.observation_space.contains(first_observation))
            self.assertEqual(first_reward, 0.0)
            self.assertFalse(terminated)
            self.assertFalse(truncated)
            self.assertEqual(first_info["total_fills"], 0)
            self.assertEqual(first_observation[6], 1.0)
            self.assertEqual(first_observation[7], 1.0)
            self.assertEqual(first_observation[8], 1.0)

            _, second_reward, terminated, truncated, second_info = env.step(2)
            self.assertEqual(second_reward, 0.0)
            self.assertFalse(terminated)
            self.assertFalse(truncated)
            self.assertEqual(second_info["fills_this_step"], 1)
            self.assertEqual(second_info["inventory"], "1")
            self.assertEqual(second_info["net_worth"], "1000.0")

            _, _, terminated, truncated, final_info = env.step(0)
            self.assertFalse(terminated)
            self.assertTrue(truncated)
            self.assertEqual(final_info["reason"], "end_of_capture")
            with self.assertRaises(RuntimeError):
                env.step(0)
            env.close()

    def test_reward_uses_exact_fee_inclusive_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            env = QueueReplayEnv(
                (path,),
                tick_size="0.5",
                quantity="1",
                simulation_config=SimulationConfig(
                    initial_cash=Decimal("1000"),
                    maker_fee_rate=Decimal("0.01"),
                    max_abs_inventory=Decimal("10"),
                ),
            )
            env.reset()
            env.step(3)
            _, reward, _, _, info = env.step(3)
            env.close()

        self.assertEqual(reward, -1.01)
        self.assertEqual(info["fees"], "1.010")
        self.assertEqual(info["net_worth"], "998.990")

    def test_direct_baseline_target_uses_the_same_step_mechanics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            env = self._environment(path)
            env.reset()
            policy = FixedSpreadPolicy(
                tick_size=Decimal("0.5"),
                quantity=Decimal("1"),
                half_spread_ticks=1,
            )
            target = policy.quote(
                env.book, env.simulator.inventory, env.current_decision_time_ns
            )
            observation, reward, terminated, truncated, info = (
                env.step_quote_target(target)
            )
            env.close()

        self.assertTrue(env.observation_space.contains(observation))
        self.assertEqual(reward, 0.0)
        self.assertFalse(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["submitted_orders"], 2)

    def test_decision_interval_replays_intervening_events_without_lookahead(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            env = QueueReplayEnv(
                (path,),
                tick_size="0.5",
                quantity="1",
                simulation_config=SimulationConfig(
                    initial_cash=Decimal("1000"),
                    max_abs_inventory=Decimal("10"),
                ),
                maximum_half_spread_ticks=2,
                maximum_absolute_skew_ticks=1,
                decision_interval_ns=4,
            )
            env.reset()
            _, reward, terminated, truncated, info = env.step(2)
            env.close()

        self.assertEqual(info["decision_time_ns"], 15)
        self.assertEqual(info["decision_interval_ns"], 4)
        self.assertEqual(info["fills_this_step"], 1)
        self.assertEqual(info["episode_steps"], 1)
        self.assertEqual(reward, 0.0)
        self.assertFalse(terminated)
        self.assertFalse(truncated)

    def test_decision_interval_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            with self.assertRaisesRegex(ValueError, "decision_interval_ns"):
                QueueReplayEnv(
                    (path,),
                    tick_size="0.5",
                    quantity="1",
                    decision_interval_ns=-1,
                )

    def test_factorized_action_schema_separates_quote_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            env = QueueReplayEnv(
                (path,),
                tick_size="0.5",
                quantity="1",
                maximum_half_spread_ticks=2,
                maximum_absolute_skew_ticks=1,
                action_schema_version=2,
            )
            env.reset()

            self.assertEqual(
                env.action_parameters(np.asarray([1, 0, 1], dtype=np.int64)),
                {"quote": True, "half_spread_ticks": 1, "skew_ticks": 0},
            )
            self.assertEqual(
                env.action_parameters(np.asarray([0, 1, 2], dtype=np.int64)),
                {"quote": False, "half_spread_ticks": 0, "skew_ticks": 0},
            )
            observation, _, _, _, info = env.step(
                np.asarray([0, 1, 2], dtype=np.int64)
            )
            env.close()

        self.assertTrue(env.observation_space.contains(observation))
        self.assertEqual(info["action_schema_version"], 2)
        self.assertEqual(info["submitted_orders"], 0)

    def test_action_schema_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            for invalid in (4, True, 1.0, "2", None):
                with self.subTest(schema=invalid):
                    with self.assertRaisesRegex(ValueError, "action_schema_version"):
                        QueueReplayEnv(
                            (path,),
                            tick_size="0.5",
                            quantity="1",
                            action_schema_version=invalid,
                        )

    def test_one_sided_actions_share_execution_and_can_reduce_inventory(self):
        from engine.simulation import Side
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            env = QueueReplayEnv((path,), tick_size="0.5", quantity="1",
                maximum_half_spread_ticks=2, maximum_absolute_skew_ticks=1,
                action_schema_version=3, observation_schema_version=2,
                simulation_config=SimulationConfig(initial_cash=Decimal("1000"), maker_fee_rate=Decimal("0.01")))
            try:
                observation, _ = env.reset()
                self.assertEqual(observation.shape, (26,))
                self.assertEqual(env.action_parameters([2, 0, 1])["side_mode"], "buy")
                self.assertEqual(env.action_parameters([3, 0, 1])["side_mode"], "sell")
                env.step([2, 0, 1])
                self.assertIsNotNone(env.simulator.open_order(Side.BUY))
                self.assertIsNone(env.simulator.open_order(Side.SELL))
                observation, reward, _, _, info = env.step([2, 0, 1])
                self.assertEqual(info["inventory"], "1")
                self.assertGreater(Decimal(info["fees"]), 0)
                self.assertLess(reward, 0)
                target = env._target(env._parse_action([3, 0, 1]))
                self.assertIsNone(target.bid_price)
                self.assertIsNotNone(target.ask_price)
                self.assertEqual(observation[20], -1)  # Only aggressive sells observed.
                self.assertTrue(env.observation_space.contains(observation))
            finally:
                env.close()

    def test_causal_market_features_ignore_future_records_and_reset_history(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first.jsonl", Path(directory) / "second.jsonl"
            _capture(first)
            _capture(second, gap=True)
            envs = [QueueReplayEnv((path,), tick_size="0.5", quantity="1",
                    observation_schema_version=2) for path in (first, second)]
            try:
                initial = [env.reset()[0] for env in envs]
                np.testing.assert_array_equal(initial[0], initial[1])
                next_obs = [env.step(0)[0] for env in envs]
                np.testing.assert_array_equal(next_obs[0], next_obs[1])
                envs[0].step(0)
                np.testing.assert_array_equal(envs[0].reset()[0], initial[0])
                for invalid in (0, 3, True, 1.0, "2"):
                    with self.assertRaisesRegex(ValueError, "observation_schema_version"):
                        QueueReplayEnv((first,), tick_size="0.5", quantity="1", observation_schema_version=invalid)
            finally:
                for env in envs:
                    env.close()

    def test_market_history_uses_elapsed_time_and_signed_public_trades(self):
        from engine.rl_trading.envs.causal_features import CausalMarketFeatures, MARKET_FEATURE_NAMES
        from engine.market_data import L2Book, parse_binance_snapshot, parse_binance_trade
        from engine.simulation import QueueAwareSimulator
        book = L2Book("binance_spot", "BTCUSDT")
        def set_book(bid, ask):
            book.load_snapshot(parse_binance_snapshot({"lastUpdateId": 100,
                "bids": [[str(bid), "5"]], "asks": [[str(ask), "5"]]}, "BTCUSDT", 0))
        state = CausalMarketFeatures()
        simulator = QueueAwareSimulator(SimulationConfig())
        set_book(10000, 10002)
        initial = state.observe(book, simulator, Decimal("10001"), Decimal("10001"), Decimal("1"), 0)
        self.assertEqual(len(initial), len(MARKET_FEATURE_NAMES))
        self.assertEqual(initial[2:8], (0.0,) * 6)
        state.trade(parse_binance_trade(_trade(1, 500_000_000), 500_000_000))
        set_book(10001, 10003)
        features = state.observe(book, simulator, Decimal("10002"), Decimal("10002"), Decimal("1"), 1_000_000_000)
        self.assertAlmostEqual(features[2], 1000 / 10001, places=6)
        self.assertGreater(features[4], features[3])  # Slower anchor lags further.
        self.assertGreater(features[3], 0)
        self.assertGreater(features[5], 0)
        self.assertEqual(features[6], -1)
        self.assertGreater(features[7], 0)
        self.assertAlmostEqual(features[11], 0.1)
        quiet = state.observe(book, simulator, Decimal("10002"), Decimal("10002"), Decimal("1"), 2_000_000_000)
        self.assertEqual(quiet[2], 0)
        self.assertEqual(quiet[6:8], (0.0, 0.0))
        self.assertLess(quiet[5], features[5])

    def test_factorized_actions_preserve_legacy_quote_and_fill_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            legacy = self._environment(path)
            factorized = QueueReplayEnv(
                (path,), tick_size="0.5", quantity="1",
                simulation_config=legacy.config,
                maximum_half_spread_ticks=2,
                maximum_absolute_skew_ticks=1,
                action_schema_version=2,
            )
            try:
                for width in range(2):
                    for skew in range(3):
                        with self.subTest(width=width, skew=skew):
                            label = 1 + width * 3 + skew
                            action = np.asarray([1, width, skew], dtype=np.int64)
                            self.assertEqual(
                                legacy.action_parameters(label),
                                factorized.action_parameters(action),
                            )
                            legacy.reset()
                            factorized.reset()
                            for _ in range(3):
                                left = legacy.step(label)
                                right = factorized.step(action)
                                np.testing.assert_array_equal(left[0], right[0])
                                self.assertEqual(left[1:4], right[1:4])
                                self.assertEqual(
                                    left[4],
                                    {**right[4], "action_schema_version": 1},
                                )
                                if left[3]:
                                    break
                check_env(factorized, skip_render_check=True)
            finally:
                legacy.close()
                factorized.close()

    def test_factorized_actions_reject_malformed_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            env = QueueReplayEnv(
                (path,), tick_size="0.5", quantity="1",
                action_schema_version=2,
            )
            try:
                env.reset()
                for invalid in (
                    1, [1, 0], [1, 0, 0, 0], [1.5, 0, 0],
                    [True, False, False], ["1", "0", "0"],
                    [2, 0, 0], [1, -1, 0], [1, 5, 0], [1, 0, 5],
                ):
                    with self.subTest(action=invalid):
                        with self.assertRaises(ValueError):
                            env.step(invalid)
                for width in range(5):
                    for skew in range(5):
                        self.assertFalse(env.action_parameters([0, width, skew])["quote"])
            finally:
                env.close()

    def test_sparse_width_grid_controls_prices_without_large_action_space(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            for schema in (1, 2):
                env = QueueReplayEnv(
                    (path,), tick_size="0.5", quantity="1",
                    maximum_half_spread_ticks=100,
                    maximum_absolute_skew_ticks=1,
                    half_spread_tick_choices=(1, 10, 100),
                    action_schema_version=schema,
                )
                try:
                    observation, _ = env.reset()
                    mid = (env.book.best_bid + env.book.best_ask) / 2
                    action = 5 if schema == 1 else [1, 1, 1]
                    self.assertEqual(env.action_parameters(action)["half_spread_ticks"], 10)
                    if schema == 1:
                        self.assertEqual(env.action_space.n, 10)
                    else:
                        np.testing.assert_array_equal(env.action_space.nvec, [2, 3, 3])
                    observation, _, _, _, _ = env.step(action)
                    self.assertTrue(env.observation_space.contains(observation))
                    self.assertEqual(
                        sorted(order.price for order in env.simulator.orders.values()),
                        [mid - Decimal("5"), mid + Decimal("5")],
                    )
                finally:
                    env.close()

    def test_sparse_width_grid_rejects_invalid_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            for choices in ((), (1, 1), (5, 1), (6,), (True,), (1.5,)):
                with self.subTest(choices=choices), self.assertRaises(ValueError):
                    QueueReplayEnv((path,), tick_size="0.5", quantity="1", half_spread_tick_choices=choices)

    def test_gap_truncates_without_a_fabricated_terminal_loss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gap.jsonl"
            _capture(path, gap=True)
            env = self._environment(path)
            env.reset()
            env.step(2)
            _, reward, terminated, truncated, info = env.step(2)

        self.assertEqual(reward, 0.0)
        self.assertFalse(terminated)
        self.assertTrue(truncated)
        self.assertEqual(info["reason"], "trade_gap")

    def test_round_robin_sessions_and_explicit_capture_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.jsonl"
            second = root / "second.jsonl"
            _capture(first)
            _capture(second, time_offset=100)
            env = QueueReplayEnv(
                (first, second), tick_size="0.5", quantity="1"
            )

            _, first_info = env.reset(seed=1)
            _, second_info = env.reset(seed=1)
            _, selected_info = env.reset(options={"capture_index": 0})
            env.close()

        self.assertEqual(first_info["capture_file"], "first.jsonl")
        self.assertEqual(second_info["capture_file"], "second.jsonl")
        self.assertEqual(selected_info["capture_file"], "first.jsonl")

    def test_each_reconnect_segment_is_a_distinct_episode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "segments.jsonl"
            _multisegment_capture(path)
            env = self._environment(path)

            _, first = env.reset()
            env.step(0)
            _, _, _, truncated, terminal = env.step(0)
            _, second = env.reset()
            _, wrapped = env.reset()
            _, selected = env.reset(
                options={"capture_index": 0, "segment_index": 1}
            )
            env.close()

        self.assertTrue(truncated)
        self.assertEqual(terminal["reason"], "disconnect")
        self.assertEqual(first["capture_segment_index"], 0)
        self.assertEqual(second["capture_segment_index"], 1)
        self.assertEqual(second["decision_time_ns"], 100)
        self.assertEqual(wrapped["capture_segment_index"], 0)
        self.assertEqual(selected["capture_segment_index"], 1)
        self.assertEqual(selected["capture_segment_count"], 2)

    def test_duplicate_capture_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.jsonl"
            second = root / "second.jsonl"
            _capture(first)
            _capture(second)
            with self.assertRaisesRegex(ValueError, "unique content"):
                QueueReplayEnv(
                    (first, second), tick_size="0.5", quantity="1"
                )

    def test_reset_replays_the_same_capture_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            env = self._environment(path)

            def replay() -> list[tuple[list[float], float, dict]]:
                env.reset(options={"capture_index": 0})
                results = []
                for action in (2, 2, 0):
                    observation, reward, _, truncated, info = env.step(action)
                    results.append((observation.tolist(), reward, info))
                    if truncated:
                        break
                return results

            first = replay()
            second = replay()
            env.close()

        self.assertEqual(first, second)

    def test_gymnasium_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            _capture(path)
            env = self._environment(path)
            check_env(env, skip_render_check=True)
            env.close()


if __name__ == "__main__":
    unittest.main()
