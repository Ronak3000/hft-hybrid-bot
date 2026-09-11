from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from engine.market_data import CaptureWriter

try:
    import gymnasium
    from gymnasium.utils.env_checker import check_env

    from engine.rl_trading.envs import QueueReplayEnv
    from engine.simulation import SimulationConfig
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
