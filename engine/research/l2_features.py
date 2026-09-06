"""Strictly causal feature extraction from verified L2 captures."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from heapq import nlargest, nsmallest
from pathlib import Path
from typing import Any, Iterator, Mapping

from engine.market_data import (
    ApplyStatus,
    L2Book,
    SchemaError,
    parse_binance_delta,
    parse_binance_snapshot,
    verify_capture,
)


FEATURE_SCHEMA_VERSION = 1
FEATURE_DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)

FEATURE_COLUMNS = (
    "event_time_ms",
    "received_time_ns",
    "update_id",
    "best_bid",
    "best_ask",
    "bid_quantity_l1",
    "ask_quantity_l1",
    "mid_price",
    "spread",
    "spread_bps",
    "microprice",
    "microprice_deviation_bps",
    "bid_depth",
    "ask_depth",
    "depth_imbalance",
    "ofi_l1",
    "bid_levels_changed",
    "ask_levels_changed",
)


@dataclass(frozen=True, slots=True)
class CausalL2Features:
    event_time_ms: int
    received_time_ns: int
    update_id: int
    best_bid: Decimal
    best_ask: Decimal
    bid_quantity_l1: Decimal
    ask_quantity_l1: Decimal
    mid_price: Decimal
    spread: Decimal
    spread_bps: Decimal
    microprice: Decimal
    microprice_deviation_bps: Decimal
    bid_depth: Decimal
    ask_depth: Decimal
    depth_imbalance: Decimal
    ofi_l1: Decimal
    bid_levels_changed: int
    ask_levels_changed: int

    def csv_row(self) -> dict[str, str | int]:
        result: dict[str, str | int] = {}
        for key, value in asdict(self).items():
            result[key] = _decimal_text(value) if isinstance(value, Decimal) else value
        return result


@dataclass(frozen=True, slots=True)
class _TopOfBook:
    bid_price: Decimal
    bid_quantity: Decimal
    ask_price: Decimal
    ask_quantity: Decimal


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _top(book: L2Book) -> _TopOfBook | None:
    best_bid = book.best_bid
    best_ask = book.best_ask
    if best_bid is None or best_ask is None:
        return None
    return _TopOfBook(
        bid_price=best_bid,
        bid_quantity=book.bids[best_bid],
        ask_price=best_ask,
        ask_quantity=book.asks[best_ask],
    )


def _ofi(previous: _TopOfBook, current: _TopOfBook) -> Decimal:
    if current.bid_price > previous.bid_price:
        bid_contribution = current.bid_quantity
    elif current.bid_price < previous.bid_price:
        bid_contribution = -previous.bid_quantity
    else:
        bid_contribution = current.bid_quantity - previous.bid_quantity

    if current.ask_price < previous.ask_price:
        ask_contribution = -current.ask_quantity
    elif current.ask_price > previous.ask_price:
        ask_contribution = previous.ask_quantity
    else:
        ask_contribution = previous.ask_quantity - current.ask_quantity
    return bid_contribution + ask_contribution


def _features(
    book: L2Book,
    previous: _TopOfBook,
    event_time_ms: int,
    received_time_ns: int,
    bid_changes: int,
    ask_changes: int,
    levels: int,
) -> tuple[CausalL2Features, _TopOfBook] | None:
    bid_levels = nlargest(levels, book.bids.items())
    ask_levels = nsmallest(levels, book.asks.items())
    if not bid_levels or not ask_levels or book.last_update_id is None:
        return None
    current = _TopOfBook(
        bid_price=bid_levels[0][0],
        bid_quantity=bid_levels[0][1],
        ask_price=ask_levels[0][0],
        ask_quantity=ask_levels[0][1],
    )

    with localcontext(FEATURE_DECIMAL_CONTEXT):
        bid_depth = sum(
            (quantity for _, quantity in bid_levels),
            Decimal(0),
        )
        ask_depth = sum(
            (quantity for _, quantity in ask_levels),
            Decimal(0),
        )
        depth_total = bid_depth + ask_depth
        top_total = current.bid_quantity + current.ask_quantity
        mid = (current.bid_price + current.ask_price) / Decimal(2)
        spread = current.ask_price - current.bid_price
        microprice = (
            current.ask_price * current.bid_quantity
            + current.bid_price * current.ask_quantity
        ) / top_total
        row = CausalL2Features(
            event_time_ms=event_time_ms,
            received_time_ns=received_time_ns,
            update_id=book.last_update_id,
            best_bid=current.bid_price,
            best_ask=current.ask_price,
            bid_quantity_l1=current.bid_quantity,
            ask_quantity_l1=current.ask_quantity,
            mid_price=mid,
            spread=spread,
            spread_bps=spread / mid * Decimal(10_000),
            microprice=microprice,
            microprice_deviation_bps=(microprice - mid) / mid * Decimal(10_000),
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            depth_imbalance=(bid_depth - ask_depth) / depth_total,
            ofi_l1=_ofi(previous, current),
            bid_levels_changed=bid_changes,
            ask_levels_changed=ask_changes,
        )
    return row, current


def iter_l2_features(path: str | Path, levels: int = 5) -> Iterator[CausalL2Features]:
    """Yield feature rows using only information available at each delta."""
    if levels <= 0:
        raise ValueError("levels must be positive")
    verify_capture(path)
    yield from _iter_l2_features_verified(path, levels)


def _iter_l2_features_verified(
    path: str | Path, levels: int
) -> Iterator[CausalL2Features]:
    """Extract rows after the caller has verified capture integrity."""
    book: L2Book | None = None
    previous: _TopOfBook | None = None

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
                if book is not None:
                    raise SchemaError("capture contains multiple metadata records")
                book = L2Book(payload["venue"], payload["symbol"])
            elif kind == "snapshot":
                if book is None:
                    raise SchemaError("snapshot appears before metadata")
                book.load_snapshot(parse_binance_snapshot(payload, book.symbol, received))
                previous = _top(book)
            elif kind == "delta":
                if book is None:
                    raise SchemaError("delta appears before metadata")
                delta = parse_binance_delta(payload, received)
                status = book.apply_delta(delta)
                if status is ApplyStatus.GAP:
                    previous = None
                if status is not ApplyStatus.APPLIED:
                    continue
                if previous is None:
                    previous = _top(book)
                    continue
                calculated = _features(
                    book,
                    previous,
                    delta.event_time_ms,
                    delta.received_time_ns,
                    len(delta.bids),
                    len(delta.asks),
                    levels,
                )
                if calculated is not None:
                    row, previous = calculated
                    yield row
            elif kind not in {"gap", "disconnect"}:
                raise SchemaError(f"unsupported record kind on line {line_number}: {kind}")


def extract_feature_csv(
    capture_path: str | Path, output_path: str | Path, levels: int = 5
) -> Mapping[str, Any]:
    """Write a deterministic feature CSV and a source-linked integrity manifest."""
    if levels <= 0:
        raise ValueError("levels must be positive")
    source_manifest = verify_capture(capture_path)
    output = Path(output_path)
    manifest_path = Path(f"{output}.manifest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        raise FileExistsError(f"feature manifest already exists: {manifest_path}")

    row_count = 0
    with output.open("x", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=FEATURE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        # The source was verified above; do not scan a large capture twice.
        for row in _iter_l2_features_verified(capture_path, levels):
            writer.writerow(row.csv_row())
            row_count += 1
        destination.flush()
        os.fsync(destination.fileno())

    raw = output.read_bytes()
    manifest: dict[str, Any] = {
        "byte_count": len(raw),
        "columns": list(FEATURE_COLUMNS),
        "feature_file": output.name,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "levels": levels,
        "row_count": row_count,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_capture": Path(capture_path).name,
        "source_metadata": source_manifest.get("metadata"),
        "source_sha256": source_manifest["sha256"],
    }
    with manifest_path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        destination.flush()
        os.fsync(destination.fileno())
    return manifest


def verify_feature_csv(
    feature_path: str | Path, capture_path: str | Path | None = None
) -> Mapping[str, Any]:
    """Verify a feature file and, optionally, its link to a source capture."""
    feature = Path(feature_path)
    manifest_path = Path(f"{feature}.manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw = feature.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read feature dataset or manifest: {exc}") from exc
    if manifest.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise ValueError("unsupported feature schema version")
    if manifest.get("feature_file") != feature.name:
        raise ValueError("feature filename does not match manifest")
    if manifest.get("columns") != list(FEATURE_COLUMNS):
        raise ValueError("feature columns do not match schema")
    if manifest.get("byte_count") != len(raw):
        raise ValueError("feature byte count does not match manifest")
    if manifest.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("feature SHA-256 does not match manifest")
    try:
        with feature.open("r", encoding="utf-8", newline="") as source:
            reader = csv.reader(source)
            header = next(reader)
            row_count = sum(1 for _ in reader)
    except (OSError, StopIteration, csv.Error) as exc:
        raise ValueError(f"cannot parse feature CSV: {exc}") from exc
    if header != list(FEATURE_COLUMNS):
        raise ValueError("feature CSV header does not match schema")
    if manifest.get("row_count") != row_count:
        raise ValueError("feature row count does not match manifest")
    if capture_path is not None:
        source = verify_capture(capture_path)
        if manifest.get("source_sha256") != source.get("sha256"):
            raise ValueError("feature manifest does not match source capture")
        if manifest.get("source_capture") != Path(capture_path).name:
            raise ValueError("source capture filename does not match feature manifest")
    return manifest
