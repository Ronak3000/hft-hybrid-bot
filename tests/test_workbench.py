"""Workbench safety, temporal coverage and user-configured PPO controls."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from engine.market_data.history import chunks, window, archive_estimate, archive_dataset, load_dataset, timestamp_ns
from engine.market_data.l2 import capture_digest

try:
    from pydantic import ValidationError
    from api.workbench import Train, launch, state, models
    from api.policy_settings import PPOSettings, SimulationSettings, command_options
except ImportError:
    Train = None


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


class ArchiveRangeTests(unittest.TestCase):
    def test_full_six_month_partition_with_no_skipped_days(self):
        start, end = utc("2024-01-01"), utc("2024-07-01")
        parts = list(chunks(start, end))
        self.assertEqual(parts[0][0], start)
        self.assertEqual(parts[-1][1], end)
        self.assertEqual(sum((b-a).total_seconds() for a,b in parts), 182*86400)
        self.assertTrue(all(a[1] == b[0] for a,b in zip(parts, parts[1:])))
        self.assertEqual(archive_estimate(start,end)["maximum_minute_requests"], 182*1440)

    def test_intraday_to_next_day_partition_is_contiguous(self):
        parts = list(chunks(utc("2024-01-01T23:57"),utc("2024-01-02T00:13")))
        self.assertEqual([int((b-a).total_seconds()/60) for a,b in parts], [3,10,3])

    def test_microsecond_and_nanosecond_timestamp_precision(self):
        self.assertEqual(timestamp_ns("2024-01-01T00:00:00.0021333Z"),1704067200002133300)

    def test_bad_ranges_are_rejected(self):
        for start,end in [(datetime(2024,1,1),utc("2024-01-02")),
                          (utc("2024-01-02"),utc("2024-01-01")),
                          (utc("2018-01-01"),utc("2024-01-01"))]:
            with self.assertRaises(ValueError):
                window(start,end)

    def test_month_without_key_fails_before_any_download(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"TARDIS_API_KEY":""}), patch("engine.market_data.history.archived_capture") as download:
            with self.assertRaisesRegex(ValueError,"TARDIS_API_KEY"):
                archive_dataset(Path(tmp), "BTCUSDT", utc("2024-01-01"), utc("2024-02-01"))
            download.assert_not_called()

    def test_modified_dataset_manifest_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ("0"*64 + ".dataset.json")
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError,"content hash"):
                load_dataset(path)

    def test_stream_hash_matches_original_algorithm(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "large"
            data = b"real input\n"*200000
            path.write_bytes(data)
            digest,size,count = capture_digest(path)
            self.assertEqual((digest,size,count),(hashlib.sha256(data).hexdigest(),len(data),200000))


@unittest.skipIf(Train is None, "API dependencies not installed")
class PolicyControlsTests(unittest.TestCase):
    def test_every_user_setting_reaches_command_options(self):
        ppo = PPOSettings(n_steps=64,batch_size=32,activation="relu",normalize_advantage=False,
                          target_kl=0.02,clip_range_vf=1.2,orthogonal_init=False)
        simulation = SimulationSettings(entry_fee_buffer_bps=2)
        options = command_options(ppo,simulation)
        for value in ("--no-normalize-advantage","--no-orthogonal-init","--target-kl","0.02","--clip-range-vf","1.2","relu","--entry-fee-buffer-bps"):
            self.assertIn(value,options)
        self.assertEqual(len([v for v in options if v.startswith("--")]),len(ppo.model_dump())+len(simulation.model_dump()))

    def test_invalid_or_unrecognized_ppo_settings_rejected(self):
        for values in [dict(n_steps=63,batch_size=32),dict(gamma=1.1),dict(learning_rate=float("nan")),dict(hidden_layers=100),dict(unknown=1)]:
            with self.assertRaises(ValidationError):
                PPOSettings(**values)

    def test_invalid_inventory_or_spread_grid_rejected(self):
        for values in [dict(quantity=1,max_abs_inventory=.1),dict(half_spread_tick_choices=[2,1]),dict(half_spread_tick_choices=[1,1])]:
            with self.assertRaises(ValidationError):
                SimulationSettings(**values)

    def test_insufficient_steps_rejected_before_launching_work(self):
        from fastapi import HTTPException
        req=Train(start=utc("2024-01-01"),end=utc("2024-02-01"))
        with patch("api.workbench.Thread") as thread:
            with self.assertRaises(HTTPException):
                launch("train",req)
            thread.assert_not_called()

    def test_unknown_job_not_reported_as_success(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            state("../other")
