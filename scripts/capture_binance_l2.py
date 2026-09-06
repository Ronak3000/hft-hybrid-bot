"""Co-capture Binance Spot L2 deltas and public trades."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
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
    parse_binance_trade,
)


REST_URL = "https://api.binance.com/api/v3/depth"
STREAM_URL = "wss://stream.binance.com:9443/stream?streams={streams}"


def _decode_stream_message(raw: str | bytes) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Binance stream message was not an object")
    event = payload.get("data", payload)
    if not isinstance(event, dict):
        raise ValueError("Binance combined-stream data was not an object")
    if event.get("e") == "serverShutdown":
        raise RecoverableCaptureError("Binance announced a stream shutdown")
    return payload


def _event_type(payload: dict[str, Any]) -> str | None:
    event = payload.get("data", payload)
    return event.get("e") if isinstance(event, dict) else None


@dataclass(slots=True)
class _ConnectionStats:
    depth_events: int = 0
    accepted_trades: int = 0
    duplicate_trades: int = 0
    out_of_order_trades: int = 0
    trade_id_gaps: int = 0
    last_trade_id: int | None = None


def _record_stream_event(
    payload: dict[str, Any],
    received: int,
    writer: CaptureWriter,
    book: L2Book,
    stats: _ConnectionStats,
) -> str:
    event_type = _event_type(payload)
    if event_type == "depthUpdate":
        writer.write("delta", payload, received)
        status = book.apply_delta(parse_binance_delta(payload, received))
        if status is ApplyStatus.GAP:
            writer.write(
                "gap",
                {"after_update_id": book.last_update_id, "reason": "depth_sequence_gap"},
                received,
            )
            return "gap"
        if status is ApplyStatus.APPLIED:
            stats.depth_events += 1
        return "continue"

    if event_type == "trade":
        trade = parse_binance_trade(payload, received)
        if trade.symbol != book.symbol or trade.venue != book.venue:
            raise ValueError("trade identity does not match the active L2 book")
        previous = stats.last_trade_id
        if previous is not None and trade.trade_id > previous + 1:
            writer.write(
                "trade_gap",
                {
                    "after_trade_id": previous,
                    "before_trade_id": trade.trade_id,
                    "missing_id_count": trade.trade_id - previous - 1,
                    "reason": "observed_trade_id_discontinuity",
                },
                received,
            )
            stats.trade_id_gaps += 1
        writer.write("trade", payload, received)
        if previous is None or trade.trade_id > previous:
            stats.accepted_trades += 1
            stats.last_trade_id = trade.trade_id
        elif trade.trade_id == previous:
            stats.duplicate_trades += 1
        else:
            stats.out_of_order_trades += 1
        return "continue"

    raise ValueError(f"unsupported Binance stream event: {event_type!r}")


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
    stats: _ConnectionStats,
) -> str:
    import websockets

    streams = f"{symbol.lower()}@depth@100ms/{symbol.lower()}@trade"
    uri = STREAM_URL.format(streams=streams)
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

            for payload, received in buffered:
                reason = _record_stream_event(payload, received, writer, book, stats)
                if reason == "gap":
                    return reason
                if stats.depth_events >= remaining:
                    return "complete"

            while stats.depth_events < remaining:
                raw = await socket.recv()
                received = time.time_ns()
                payload = _decode_stream_message(raw)
                reason = _record_stream_event(payload, received, writer, book, stats)
                if reason == "gap":
                    return reason
            return "complete"
    except (OSError, websockets.WebSocketException) as exc:
        raise RecoverableCaptureError("depth stream disconnected") from exc


async def capture(
    symbol: str, output: Path, events: int, limit: int, max_reconnects: int
) -> None:
    metadata = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "depth_limit": limit,
        "source": "Binance Spot REST snapshot + combined diff-depth/trade WebSocket",
        "streams": [f"{symbol.lower()}@depth@100ms", f"{symbol.lower()}@trade"],
        "symbol": symbol,
        "venue": "binance_spot",
    }
    accepted = 0
    trades = duplicate_trades = out_of_order_trades = trade_id_gaps = 0
    reconnects = 0
    with CaptureWriter(output, metadata) as writer:
        while accepted < events:
            stats = _ConnectionStats()
            try:
                reason = await _connect_and_capture(
                    symbol, limit, writer, events - accepted, stats
                )
            except RecoverableCaptureError as exc:
                reason = "disconnect"
                writer.write(
                    "disconnect",
                    {"error_type": type(exc).__name__, "reconnect": reconnects + 1},
                    time.time_ns(),
                )
            finally:
                accepted += stats.depth_events
                trades += stats.accepted_trades
                duplicate_trades += stats.duplicate_trades
                out_of_order_trades += stats.out_of_order_trades
                trade_id_gaps += stats.trade_id_gaps
            if reason == "complete":
                break
            reconnects += 1
            if reconnects > max_reconnects:
                raise RuntimeError(
                    f"capture aborted after {reconnects} resynchronizations"
                )
            await asyncio.sleep(min(2**min(reconnects, 4), 16))
    print(f"Captured {accepted} applied L2 deltas and {trades} accepted public trades.")
    print(
        "Trade diagnostics: "
        f"{trade_id_gaps} ID gaps, {duplicate_trades} duplicates, "
        f"{out_of_order_trades} out-of-order events."
    )
    print(f"Depth resynchronizations/reconnects: {reconnects}.")
    print(f"Capture: {output}")
    print(f"Manifest: {output}.manifest.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Co-capture Binance Spot L2 snapshots/deltas and public trades."
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
