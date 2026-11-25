"""Download real Binance Spot depth/trades from Tardis' raw minute archive.

Replay from UTC midnight to establish the exchange sequence. Only the selected
window (exclusive end) reaches the policy. Never interpolate missing minutes.
"""
import json
import os
import hashlib
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

from .l2 import (ApplyStatus, CaptureWriter, L2Book, parse_binance_delta,
                 parse_binance_snapshot, parse_binance_trade, replay_capture, verify_capture)

SOURCE = "Tardis raw Binance Spot depthSnapshot/depth/trade"


def window(start, end):
    if any(t.tzinfo is None or t.utcoffset() is None for t in (start, end)):
        raise ValueError("Specify a timezone for both endpoints.")
    start, end = (t.astimezone(timezone.utc) for t in (start, end))
    if any(t.second or t.microsecond for t in (start, end)):
        raise ValueError("Use whole-minute UTC boundaries.")
    if end - start < timedelta(minutes=1):
        raise ValueError("Choose at least one completed minute.")
    if end > datetime.now(timezone.utc):
        raise ValueError("The interval cannot end in the future.")
    if start < datetime(2019, 3, 30, tzinfo=timezone.utc):
        raise ValueError("Binance Spot archive starts on 2019-03-30.")
    return start, end


def timestamp_ns(stamp):
    seconds, fraction = stamp.removesuffix("Z").split(".")
    return int(datetime.fromisoformat(seconds).replace(tzinfo=timezone.utc).timestamp()) * 10**9 + int(fraction.ljust(9, "0"))


def archived_capture(root: Path, symbol: str, start, end, progress=lambda message: None,
                     *, prior_capture=None, check=lambda: None):
    start, end = window(start, end)
    if end - start > timedelta(minutes=10) or start.date() != (end - timedelta(microseconds=1)).date():
        raise ValueError("Archive chunks must be at most ten minutes within one UTC day.")
    if symbol != "BTCUSDT":
        raise ValueError("Only BTCUSDT has a configured tick size and position limit.")
    name = f"{symbol}-{start:%Y%m%dT%H%M}-{end:%H%M}"
    target = root / name
    path = target / (name + ".jsonl")
    if path.exists():
        validate(path)
        return path
    root.mkdir(parents=True, exist_ok=True)
    midnight = start.replace(hour=0, minute=0)
    slices = int((end - midnight).total_seconds() // 60)
    start_ns = int(start.timestamp()) * 10**9
    params = {"from": midnight.strftime("%Y-%m-%dT00:00:00.000Z"),
              "filters": json.dumps([{"channel": c, "symbols": [symbol.lower()]}
                                     for c in ("depth", "depthSnapshot", "trade")])}
    meta = dict(venue="binance_spot", symbol=symbol, source=SOURCE,
                start=start.isoformat(), end=end.isoformat(), snapshot_basis="sequence-replayed Binance REST snapshot and diff-depth")
    # Publish capture and manifest together, only after every requested minute validates.
    with TemporaryDirectory(dir=root) as tmp, requests.Session() as session:
        staging = Path(tmp) / name
        staged = staging / path.name
        key = os.getenv("TARDIS_API_KEY")
        if key:
            session.headers["Authorization"] = "Bearer " + key
        book = L2Book("binance_spot", symbol)
        buffered = []
        emitted = bridged = False
        previous_trade = None
        first_offset = 0
        if prior_capture is not None and start != midnight:
            previous = verify_capture(prior_capture)["metadata"]
            if previous["symbol"] != symbol or datetime.fromisoformat(previous["end"]) != start:
                raise ValueError("Archive continuation does not match the previous interval.")
            book = validate(prior_capture).book
            bridged = True
            # Carry the trade ID over chunk boundaries, not just the book.
            with Path(prior_capture).open(encoding="utf-8") as source:
                for line in source:
                    record = json.loads(line)
                    if record["kind"] == "trade":
                        previous_trade = parse_binance_trade(record["payload"], record["received_time_ns"]).trade_id
            first_offset = int((start - midnight).total_seconds() // 60)
        with CaptureWriter(staged, meta) as writer:
            for offset in range(first_offset, slices):
                check()
                progress(f"Fetching archive minute {offset + 1}/{slices} (including book warm-up)")
                with session.get("https://api.tardis.dev/v1/data-feeds/binance",
                                 params={**params, "offset": offset}, timeout=(10, 30), stream=True) as response:
                    if response.status_code in (401, 403):
                        raise ValueError("Archive access denied for this date. Use a free first-of-month window or configure TARDIS_API_KEY.")
                    response.raise_for_status()
                    seen = False
                    previous_ns = -1
                    bytes_received = 0
                    for line in response.iter_lines(chunk_size=65536):
                        check()
                        bytes_received += len(line)
                        if bytes_received > 128 * 1024 * 1024:
                            raise ValueError("Archive minute exceeded the safety size limit.")
                        if not line:
                            if emitted:
                                raise ValueError("Exchange disconnected within the selected window.")
                            book = L2Book("binance_spot", symbol)
                            buffered.clear()
                            bridged = False
                            previous_trade = None
                            continue
                        stamp, raw = line.split(b" ", 1)
                        ns = timestamp_ns(stamp.decode())
                        if ns < previous_ns:
                            raise ValueError("Archive receive time regressed.")
                        previous_ns = ns
                        if ns // (60 * 10**9) != int(midnight.timestamp()) // 60 + offset:
                            raise ValueError("Archive record outside requested minute.")
                        seen = True
                        event = json.loads(raw)
                        channel = event["stream"]
                        if not channel.startswith(symbol.lower() + "@"):
                            raise ValueError("Archive symbol mismatch.")
                        if channel.endswith("@depthSnapshot"):
                            if emitted:
                                raise ValueError("Snapshot discontinuity within requested window.")
                            book.load_snapshot(parse_binance_snapshot(event["data"], symbol, ns))
                            bridged = False
                            for delta in buffered:
                                status = book.apply_delta(delta)
                                if status is ApplyStatus.GAP:
                                    raise ValueError("Archive snapshot cannot bridge depth sequence.")
                                bridged |= status is ApplyStatus.APPLIED
                            buffered.clear()
                            continue
                        if not emitted and ns >= start_ns and bridged:
                            writer.write("snapshot", {"lastUpdateId": book.last_update_id,
                                         "bids": [[str(p), str(q)] for p, q in book.bids.items()],
                                         "asks": [[str(p), str(q)] for p, q in book.asks.items()]}, ns)
                            emitted = True
                        if event["data"]["e"] == "depthUpdate":
                            delta = parse_binance_delta(event, ns)
                            if not book.synchronized:
                                buffered.append(delta)
                                if len(buffered) > 2000:
                                    raise ValueError("No initial exchange snapshot.")
                                continue
                            status = book.apply_delta(delta)
                            if status is ApplyStatus.GAP:
                                raise ValueError("Depth sequence gap; refusing incomplete history.")
                            bridged |= status is ApplyStatus.APPLIED
                            if emitted:
                                writer.write("delta", event, ns)
                        else:
                            trade = parse_binance_trade(event, ns)
                            if trade.symbol != symbol or (previous_trade is not None and trade.trade_id != previous_trade + 1):
                                raise ValueError("Discontinuous or mismatched public trades.")
                            previous_trade = trade.trade_id
                            if emitted:
                                writer.write("trade", event, ns)
                    if not seen:
                        raise ValueError("Archive has no records for a requested minute.")
        validate(staged)
        staging.rename(target)
    return path


def validate(path):
    result = replay_capture(path)
    if (result.snapshots != 1 or not result.applied_deltas or not result.accepted_trades
            or result.gaps or result.trade_id_gaps or result.duplicate_trades or result.out_of_order_trades):
        raise ValueError("Historical window lacks continuous verified Binance depth and trades.")
    return result


def chunks(start, end):
    """Partition the complete selected range; no sampling or silent date skips."""
    start, end = window(start, end)
    while start < end:
        midnight = (start + timedelta(days=1)).replace(hour=0, minute=0)
        stop = min(start + timedelta(minutes=10), midnight, end)
        yield start, stop
        start = stop


def archive_estimate(start, end):
    parts = list(chunks(start, end))
    days = sorted({a.date() for a, _ in parts})
    minutes = int((end - start).total_seconds() // 60)
    return {"selected_minutes": minutes, "archive_days": len(days), "chunks": len(parts),
            "maximum_minute_requests": minutes + start.hour * 60 + start.minute,
            "requires_archive_key": any(day.day != 1 for day in days),
            "archive_key_configured": bool(os.getenv("TARDIS_API_KEY")),
            "data_mode": "complete_range_not_sampled",
            "execution": "independent ten-minute paper episodes; portfolio resets at chunk boundaries",
            "warning": "Months of tick-level L2 may need substantial disk space and time. Download finishes before PPO starts."}


def archive_dataset(root, symbol, start, end, progress=lambda message: None, *,
                    max_download_bytes=100 * 1024**3, check=lambda: None):
    start, end = window(start, end)
    estimate = archive_estimate(start, end)
    if estimate["requires_archive_key"] and not estimate["archive_key_configured"]:
        raise ValueError("This range includes dates requiring TARDIS_API_KEY. Configure archive access; no dates will be skipped or substituted.")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    total = 0
    paths = []
    previous = None
    for index, (a, b) in enumerate(chunks(start, end)):
        check()
        progress(f"Downloading verified chunk {index + 1}/{estimate['chunks']}: {a.isoformat()}")
        last_disk_check = 0.0
        def guard():
            nonlocal last_disk_check
            check()
            now = time.monotonic()
            if now - last_disk_check > 1:
                last_disk_check = now
                if shutil.disk_usage(root).free < 512 * 1024**2:
                    raise ValueError("Less than 512 MiB disk space remains; download stopped.")
        if total >= max_download_bytes:
            raise ValueError("Dataset exceeds selected disk budget; verified chunks retained for retry.")
        path = archived_capture(root / "captures", symbol, a, b, progress,
                                prior_capture=previous, check=guard)
        manifest = verify_capture(path)
        total += manifest["byte_count"]
        if total > max_download_bytes:
            raise ValueError("Dataset exceeds selected disk budget; verified chunks retained for retry.")
        paths.append({"path": str(path.relative_to(root)), "sha256": manifest["sha256"],
                      "start": a.isoformat(), "end": b.isoformat()})
        previous = path
    payload = {"schema_version": 1, "source": SOURCE, "symbol": symbol, "start": start.isoformat(),
               "end": end.isoformat(), "captures": paths, "byte_count": total,
               "coverage": "complete_selected_range", "episode_reset_minutes": 10}
    raw = json.dumps(payload, sort_keys=True).encode()
    manifest_path = root / (hashlib.sha256(raw).hexdigest() + ".dataset.json")
    if not manifest_path.exists():
        with manifest_path.open("xb") as destination:
            destination.write(raw)
    return manifest_path


def load_dataset(path):
    path = Path(path)
    raw = path.read_bytes()
    if path.name != hashlib.sha256(raw).hexdigest() + ".dataset.json":
        raise ValueError("Dataset manifest content hash mismatch.")
    meta = json.loads(raw)
    expected = list(chunks(datetime.fromisoformat(meta["start"]), datetime.fromisoformat(meta["end"])))
    if len(expected) != len(meta["captures"]):
        raise ValueError("Incomplete dataset coverage.")
    paths = []
    for item, (a, b) in zip(meta["captures"], expected):
        capture = (path.parent / item["path"]).resolve()
        if not capture.is_relative_to(path.parent.resolve()):
            raise ValueError("Dataset path is outside its archive directory.")
        data = verify_capture(capture)
        m = data["metadata"]
        if (item["sha256"] != data["sha256"] or m["symbol"] != meta["symbol"] or m["source"] != SOURCE
                or m["start"] != a.isoformat() or m["end"] != b.isoformat()
                or item["start"] != m["start"] or item["end"] != m["end"]):
            raise ValueError("Dataset source, hash or temporal coverage mismatch.")
        paths.append(capture)
    return meta, tuple(paths)
