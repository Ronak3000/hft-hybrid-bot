"""Capture sequence-valid Binance Spot L2 snapshots and depth deltas."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.market_data.l2 import (
    ApplyStatus,
    CaptureWriter,
    L2Book,
    RecoverableCaptureError,
    parse_binance_delta,
    parse_binance_snapshot,
)


REST_URL = "https://api.binance.com/api/v3/depth"
STREAM_URL = "wss://stream.binance.com:9443/ws/{stream}"


def _decode_stream_message(raw: str | bytes) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Binance stream message was not an object")
    if payload.get("e") == "serverShutdown":
        raise RecoverableCaptureError("Binance announced a stream shutdown")
    return payload


def _snapshot(symbol: str, limit: int) -> tuple[dict[str, Any], int]:
    import requests

    try:
        response = requests.get(
            REST_URL, params={"symbol": symbol, "limit": limit}, timeout=15
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RecoverableCaptureError("snapshot request failed") from exc
    received_time_ns = time.time_ns()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Binance snapshot response was not an object")
    return payload, received_time_ns


async def _connect_and_capture(
    symbol: str,
    limit: int,
    writer: CaptureWriter,
    remaining: int,
) -> tuple[int, str]:
    import websockets

    stream = f"{symbol.lower()}@depth@100ms"
    uri = STREAM_URL.format(stream=stream)
    buffered: list[tuple[dict[str, Any], int]] = []

    try:
        socket_context = websockets.connect(uri, ping_interval=20, ping_timeout=20)
        async with socket_context as socket:
            snapshot_task = asyncio.create_task(asyncio.to_thread(_snapshot, symbol, limit))
            while not snapshot_task.done():
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
                received = time.time_ns()
                buffered.append((_decode_stream_message(raw), received))

            snapshot_payload, snapshot_received = await snapshot_task
            snapshot = parse_binance_snapshot(snapshot_payload, symbol, snapshot_received)
            book = L2Book("binance_spot", symbol)
            book.load_snapshot(snapshot)
            writer.write("snapshot", snapshot_payload, snapshot_received)

            accepted = 0
            for payload, received in buffered:
                writer.write("delta", payload, received)
                status = book.apply_delta(parse_binance_delta(payload, received))
                if status is ApplyStatus.GAP:
                    writer.write(
                        "gap",
                        {"after_update_id": book.last_update_id, "reason": "sequence_gap"},
                        time.time_ns(),
                    )
                    return accepted, "gap"
                if status is ApplyStatus.APPLIED:
                    accepted += 1
                    if accepted >= remaining:
                        return accepted, "complete"

            while accepted < remaining:
                raw = await socket.recv()
                received = time.time_ns()
                payload = _decode_stream_message(raw)
                writer.write("delta", payload, received)
                status = book.apply_delta(parse_binance_delta(payload, received))
                if status is ApplyStatus.GAP:
                    writer.write(
                        "gap",
                        {"after_update_id": book.last_update_id, "reason": "sequence_gap"},
                        time.time_ns(),
                    )
                    return accepted, "gap"
                if status is ApplyStatus.APPLIED:
                    accepted += 1
            return accepted, "complete"
    except (OSError, websockets.WebSocketException) as exc:
        raise RecoverableCaptureError("depth stream disconnected") from exc


async def capture(
    symbol: str, output: Path, events: int, limit: int, max_reconnects: int
) -> None:
    metadata = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "depth_limit": limit,
        "source": "Binance Spot REST snapshot + diff-depth WebSocket",
        "symbol": symbol,
        "venue": "binance_spot",
    }
    accepted = 0
    reconnects = 0
    with CaptureWriter(output, metadata) as writer:
        while accepted < events:
            try:
                count, reason = await _connect_and_capture(
                    symbol, limit, writer, events - accepted
                )
                accepted += count
                if reason == "complete":
                    break
                reconnects += 1
            except RecoverableCaptureError as exc:
                reconnects += 1
                writer.write(
                    "disconnect",
                    {"error_type": type(exc).__name__, "reconnect": reconnects},
                    time.time_ns(),
                )
            if reconnects > max_reconnects:
                raise RuntimeError(
                    f"capture aborted after {reconnects} resynchronizations"
                )
            await asyncio.sleep(min(2**min(reconnects, 4), 16))
    print(f"Captured {accepted} applied L2 deltas with {reconnects} resynchronizations.")
    print(f"Capture: {output}")
    print(f"Manifest: {output}.manifest.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture genuine Binance Spot L2 snapshots and deltas."
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--events", type=int, default=1_000)
    parser.add_argument("--depth-limit", type=int, default=1_000, choices=(100, 500, 1000, 5000))
    parser.add_argument("--max-reconnects", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.events <= 0:
        parser.error("--events must be positive")
    if args.max_reconnects < 0:
        parser.error("--max-reconnects must be non-negative")
    asyncio.run(
        capture(
            args.symbol.upper(),
            args.output,
            args.events,
            args.depth_limit,
            args.max_reconnects,
        )
    )


if __name__ == "__main__":
    main()
