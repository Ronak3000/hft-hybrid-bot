"""Venue L2 schemas, sequence validation, immutable capture, and replay.

This module models aggregated price levels, not individual exchange orders or
queue positions. It intentionally lives outside the C++ matching hot path.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, TextIO


SCHEMA_VERSION = 1
_MISSING = object()


class SchemaError(ValueError):
    """An exchange payload or capture record violates the L2 schema."""


class CaptureIntegrityError(ValueError):
    """A capture does not match its immutable manifest."""


class RecoverableCaptureError(RuntimeError):
    """A network interruption for which a fresh connection is appropriate."""


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise SchemaError(f"{field} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{field} must be a positive integer") from exc
    if parsed <= 0 or (isinstance(value, float) and not value.is_integer()):
        raise SchemaError(f"{field} must be a positive integer")
    return parsed


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise SchemaError(f"{field} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{field} must be a non-negative integer") from exc
    if parsed < 0 or (isinstance(value, float) and not value.is_integer()):
        raise SchemaError(f"{field} must be a non-negative integer")
    return parsed


def _decimal(value: Any, field: str, *, allow_zero: bool) -> Decimal:
    if isinstance(value, float) and not math.isfinite(value):
        raise SchemaError(f"{field} must be finite")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SchemaError(f"{field} must be a decimal number") from exc
    if not parsed.is_finite() or parsed < 0 or (not allow_zero and parsed == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise SchemaError(f"{field} must be a finite {qualifier} decimal")
    return parsed


def _symbol(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError("symbol must be a non-empty string")
    return value.strip().upper()


@dataclass(frozen=True, slots=True)
class Level:
    price: Decimal
    quantity: Decimal

    @classmethod
    def from_pair(cls, pair: Any, field: str) -> "Level":
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise SchemaError(f"{field} entries must be [price, quantity] pairs")
        return cls(
            price=_decimal(pair[0], f"{field}.price", allow_zero=False),
            quantity=_decimal(pair[1], f"{field}.quantity", allow_zero=True),
        )


def _levels(raw: Any, field: str, *, snapshot: bool) -> tuple[Level, ...]:
    if not isinstance(raw, list):
        raise SchemaError(f"{field} must be a list")
    parsed = tuple(Level.from_pair(pair, field) for pair in raw)
    if snapshot and any(level.quantity == 0 for level in parsed):
        raise SchemaError(f"snapshot {field} quantities must be positive")
    prices = [level.price for level in parsed]
    if len(prices) != len(set(prices)):
        raise SchemaError(f"{field} contains duplicate prices")
    return parsed


@dataclass(frozen=True, slots=True)
class L2Snapshot:
    venue: str
    symbol: str
    received_time_ns: int
    last_update_id: int
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]


@dataclass(frozen=True, slots=True)
class L2Delta:
    venue: str
    symbol: str
    received_time_ns: int
    event_time_ms: int
    first_update_id: int
    final_update_id: int
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]


def parse_binance_snapshot(
    payload: Mapping[str, Any], symbol: str, received_time_ns: int
) -> L2Snapshot:
    if not isinstance(payload, Mapping):
        raise SchemaError("snapshot payload must be an object")
    return L2Snapshot(
        venue="binance_spot",
        symbol=_symbol(symbol),
        received_time_ns=_nonnegative_int(received_time_ns, "received_time_ns"),
        last_update_id=_positive_int(payload.get("lastUpdateId"), "lastUpdateId"),
        bids=_levels(payload.get("bids"), "bids", snapshot=True),
        asks=_levels(payload.get("asks"), "asks", snapshot=True),
    )


def parse_binance_delta(payload: Mapping[str, Any], received_time_ns: int) -> L2Delta:
    if not isinstance(payload, Mapping):
        raise SchemaError("delta payload must be an object")
    if "data" in payload:
        payload = payload["data"]
        if not isinstance(payload, Mapping):
            raise SchemaError("combined-stream data must be an object")
    if payload.get("e") != "depthUpdate":
        raise SchemaError("event is not a Binance depthUpdate")
    first = _positive_int(payload.get("U"), "U")
    final = _positive_int(payload.get("u"), "u")
    if first > final:
        raise SchemaError("U must not exceed u")
    return L2Delta(
        venue="binance_spot",
        symbol=_symbol(payload.get("s")),
        received_time_ns=_nonnegative_int(received_time_ns, "received_time_ns"),
        event_time_ms=_nonnegative_int(payload.get("E"), "E"),
        first_update_id=first,
        final_update_id=final,
        bids=_levels(payload.get("b"), "b", snapshot=False),
        asks=_levels(payload.get("a"), "a", snapshot=False),
    )


class ApplyStatus(str, Enum):
    APPLIED = "applied"
    STALE = "stale"
    GAP = "gap"
    NEED_SNAPSHOT = "need_snapshot"


class L2Book:
    """A deterministic aggregated book with explicit synchronization state."""

    def __init__(self, venue: str, symbol: str) -> None:
        self.venue = venue
        self.symbol = _symbol(symbol)
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.last_update_id: int | None = None
        self.synchronized = False

    def load_snapshot(self, snapshot: L2Snapshot) -> None:
        self._check_identity(snapshot.venue, snapshot.symbol)
        bids = {level.price: level.quantity for level in snapshot.bids}
        asks = {level.price: level.quantity for level in snapshot.asks}
        self._validate_not_crossed(bids, asks)
        self.bids = bids
        self.asks = asks
        self.last_update_id = snapshot.last_update_id
        self.synchronized = True

    def apply_delta(self, delta: L2Delta) -> ApplyStatus:
        self._check_identity(delta.venue, delta.symbol)
        if not self.synchronized or self.last_update_id is None:
            return ApplyStatus.NEED_SNAPSHOT

        if delta.final_update_id <= self.last_update_id:
            return ApplyStatus.STALE

        expected = self.last_update_id + 1
        if delta.first_update_id > expected:
            self.synchronized = False
            return ApplyStatus.GAP

        changes: list[tuple[dict[Decimal, Decimal], Decimal, Decimal | object]] = []
        try:
            self._apply_levels(self.bids, delta.bids, changes)
            self._apply_levels(self.asks, delta.asks, changes)
            self._validate_not_crossed(self.bids, self.asks)
        except Exception:
            for side, price, previous in reversed(changes):
                if previous is _MISSING:
                    side.pop(price, None)
                else:
                    side[price] = previous  # type: ignore[assignment]
            raise
        self.last_update_id = delta.final_update_id
        return ApplyStatus.APPLIED

    @property
    def best_bid(self) -> Decimal | None:
        return max(self.bids, default=None)

    @property
    def best_ask(self) -> Decimal | None:
        return min(self.asks, default=None)

    def state_digest(self) -> str:
        state = {
            "asks": [[_decimal_text(p), _decimal_text(self.asks[p])] for p in sorted(self.asks)],
            "bids": [[_decimal_text(p), _decimal_text(self.bids[p])] for p in sorted(self.bids, reverse=True)],
            "last_update_id": self.last_update_id,
            "symbol": self.symbol,
            "synchronized": self.synchronized,
            "venue": self.venue,
        }
        encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _check_identity(self, venue: str, symbol: str) -> None:
        if venue != self.venue or _symbol(symbol) != self.symbol:
            raise SchemaError(
                f"book identity {self.venue}:{self.symbol} does not match {venue}:{symbol}"
            )

    @staticmethod
    def _apply_levels(
        book: dict[Decimal, Decimal],
        levels: Iterable[Level],
        changes: list[tuple[dict[Decimal, Decimal], Decimal, Decimal | object]],
    ) -> None:
        for level in levels:
            changes.append((book, level.price, book.get(level.price, _MISSING)))
            if level.quantity == 0:
                book.pop(level.price, None)
            else:
                book[level.price] = level.quantity

    @staticmethod
    def _validate_not_crossed(
        bids: Mapping[Decimal, Decimal], asks: Mapping[Decimal, Decimal]
    ) -> None:
        if bids and asks and max(bids) >= min(asks):
            raise SchemaError("L2 state is crossed or locked")


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _canonical_line(record: Mapping[str, Any]) -> bytes:
    return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class CaptureWriter:
    """Exclusive-create, append-only JSONL writer with a SHA-256 manifest."""

    def __init__(self, path: str | Path, metadata: Mapping[str, Any]) -> None:
        self.path = Path(path)
        self.manifest_path = Path(f"{self.path}.manifest.json")
        self._metadata = {"schema_version": SCHEMA_VERSION, **dict(metadata)}
        # Fail before creating a partial capture if metadata cannot be encoded.
        _canonical_line(
            {"kind": "metadata", "payload": self._metadata, "received_time_ns": 0}
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.manifest_path.exists():
            raise FileExistsError(f"capture manifest already exists: {self.manifest_path}")
        self._file: TextIO = self.path.open("x", encoding="utf-8", newline="\n")
        self._records = 0
        self._closed = False
        self.write("metadata", self._metadata, 0)

    def write(self, kind: str, payload: Mapping[str, Any], received_time_ns: int) -> None:
        if self._closed:
            raise RuntimeError("capture writer is closed")
        if kind not in {"metadata", "snapshot", "delta", "gap", "disconnect"}:
            raise ValueError(f"unsupported capture record kind: {kind}")
        record = {
            "kind": kind,
            "payload": dict(payload),
            "received_time_ns": _nonnegative_int(received_time_ns, "received_time_ns"),
        }
        line = _canonical_line(record)
        self._file.write(line.decode("utf-8"))
        self._file.flush()
        self._records += 1

    def close(self) -> Path:
        if self._closed:
            return self.manifest_path
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        raw = self.path.read_bytes()
        manifest = {
            "byte_count": len(raw),
            "capture_file": self.path.name,
            "metadata": self._metadata,
            "record_count": self._records,
            "schema_version": SCHEMA_VERSION,
            # Hash the bytes from disk rather than relying on text newline behavior.
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        with self.manifest_path.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())
        self._closed = True
        return self.manifest_path

    def __enter__(self) -> "CaptureWriter":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def verify_capture(path: str | Path) -> Mapping[str, Any]:
    capture_path = Path(path)
    manifest_path = Path(f"{capture_path}.manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureIntegrityError(f"cannot read capture manifest: {exc}") from exc
    try:
        raw = capture_path.read_bytes()
    except OSError as exc:
        raise CaptureIntegrityError(f"cannot read capture: {exc}") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise CaptureIntegrityError("unsupported capture schema version")
    if manifest.get("capture_file") != capture_path.name:
        raise CaptureIntegrityError("manifest capture filename does not match")
    if manifest.get("byte_count") != len(raw):
        raise CaptureIntegrityError("capture byte count does not match manifest")
    if manifest.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise CaptureIntegrityError("capture SHA-256 does not match manifest")
    if manifest.get("record_count") != raw.count(b"\n"):
        raise CaptureIntegrityError("capture record count does not match manifest")
    return manifest


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    book: L2Book
    snapshots: int
    applied_deltas: int
    stale_deltas: int
    gaps: int


def replay_capture(path: str | Path) -> ReplaySummary:
    verify_capture(path)
    book: L2Book | None = None
    snapshots = applied = stale = gaps = 0
    with Path(path).open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                record = json.loads(line)
                kind = record["kind"]
                payload = record["payload"]
                received = record["received_time_ns"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise SchemaError(f"invalid capture record on line {line_number}") from exc
            if kind == "metadata":
                if book is None:
                    book = L2Book(payload["venue"], payload["symbol"])
            elif kind == "snapshot":
                if book is None:
                    raise SchemaError("snapshot appears before metadata")
                book.load_snapshot(parse_binance_snapshot(payload, book.symbol, received))
                snapshots += 1
            elif kind == "delta":
                if book is None:
                    raise SchemaError("delta appears before metadata")
                status = book.apply_delta(parse_binance_delta(payload, received))
                if status is ApplyStatus.APPLIED:
                    applied += 1
                elif status is ApplyStatus.STALE:
                    stale += 1
                elif status is ApplyStatus.GAP:
                    gaps += 1
            elif kind == "gap":
                continue
            elif kind == "disconnect":
                continue
            else:
                raise SchemaError(f"unsupported record kind on line {line_number}: {kind}")
    if book is None:
        raise SchemaError("capture has no metadata record")
    return ReplaySummary(book, snapshots, applied, stale, gaps)
