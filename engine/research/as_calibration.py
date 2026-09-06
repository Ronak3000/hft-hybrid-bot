"""Training-only calibration for the Avellaneda–Stoikov baseline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from typing import Any, Iterable, Mapping

from engine.market_data import (
    ApplyStatus,
    L2Book,
    SchemaError,
    parse_binance_delta,
    parse_binance_snapshot,
    parse_binance_trade,
    verify_capture,
)


CALIBRATION_SCHEMA_VERSION = 1
CALIBRATION_DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class DistanceIntensity:
    distance: Decimal
    reached_trades: int
    per_side_intensity_per_second: Decimal


@dataclass(frozen=True, slots=True)
class ASCalibration:
    volatility_per_sqrt_second: Decimal
    intensity_decay: Decimal
    intensity_scale_per_second: Decimal
    intensity_fit_r_squared: Decimal
    active_exposure_seconds: Decimal
    variance_observations: int
    active_trade_events: int
    distance_intensities: tuple[DistanceIntensity, ...]
    source_captures: tuple[Mapping[str, Any], ...]

    def report(self) -> dict[str, Any]:
        return {
            "calibration_schema_version": CALIBRATION_SCHEMA_VERSION,
            "method": {
                "volatility": "sqrt(sum(mid_change^2) / sum(local_receive_dt_seconds))",
                "arrival_model": "per-side lambda(distance) = A * exp(-k * distance)",
                "arrival_fit": "ordinary least squares on log positive-bin intensities",
                "queue_note": (
                    "public aggressive-trade reach, not exact hypothetical "
                    "fill intensity"
                ),
            },
            "volatility_per_sqrt_second": str(self.volatility_per_sqrt_second),
            "intensity_decay": str(self.intensity_decay),
            "intensity_scale_per_second": str(self.intensity_scale_per_second),
            "intensity_fit_r_squared": str(self.intensity_fit_r_squared),
            "active_exposure_seconds": str(self.active_exposure_seconds),
            "variance_observations": self.variance_observations,
            "active_trade_events": self.active_trade_events,
            "distance_intensities": [
                {
                    "distance": str(item.distance),
                    "reached_trades": item.reached_trades,
                    "per_side_intensity_per_second": str(
                        item.per_side_intensity_per_second
                    ),
                }
                for item in self.distance_intensities
            ],
            "source_captures": [dict(item) for item in self.source_captures],
        }


@dataclass(slots=True)
class _CaptureStatistics:
    squared_mid_changes: Decimal
    variance_time_seconds: Decimal
    variance_observations: int
    active_exposure_seconds: Decimal
    active_trade_events: int
    reached_counts: list[int]


def calibrate_avellaneda_stoikov(
    capture_paths: Iterable[str | Path], distances: Iterable[Decimal | str]
) -> ASCalibration:
    paths = tuple(Path(path) for path in capture_paths)
    if not paths:
        raise ValueError("at least one training capture is required")
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("training captures must not contain duplicates")
    parsed_distances = tuple(
        sorted({_positive_decimal(value, "distance") for value in distances})
    )
    if len(parsed_distances) < 2:
        raise ValueError("at least two unique positive distances are required")

    squared_changes = variance_seconds = exposure_seconds = Decimal("0")
    variance_observations = active_trades = 0
    reached_counts = [0 for _ in parsed_distances]
    sources: list[Mapping[str, Any]] = []
    source_hashes: set[str] = set()
    for path in paths:
        manifest = verify_capture(path)
        if manifest["sha256"] in source_hashes:
            raise ValueError("training captures must have unique content")
        source_hashes.add(manifest["sha256"])
        statistics = _capture_statistics(path, parsed_distances)
        with localcontext(CALIBRATION_DECIMAL_CONTEXT):
            squared_changes += statistics.squared_mid_changes
            variance_seconds += statistics.variance_time_seconds
            exposure_seconds += statistics.active_exposure_seconds
        variance_observations += statistics.variance_observations
        active_trades += statistics.active_trade_events
        reached_counts = [
            total + value
            for total, value in zip(reached_counts, statistics.reached_counts)
        ]
        sources.append(
            {
                "capture_file": path.name,
                "sha256": manifest["sha256"],
                "metadata": manifest["metadata"],
            }
        )

    if variance_observations == 0 or variance_seconds <= 0 or squared_changes <= 0:
        raise ValueError("training captures contain no positive-time mid-price changes")
    if exposure_seconds <= 0:
        raise ValueError("training captures contain no active exposure time")
    with localcontext(CALIBRATION_DECIMAL_CONTEXT):
        volatility = (squared_changes / variance_seconds).sqrt()
        denominator = Decimal("2") * exposure_seconds
        intensities = tuple(
            DistanceIntensity(
                distance=distance,
                reached_trades=count,
                per_side_intensity_per_second=Decimal(count) / denominator,
            )
            for distance, count in zip(parsed_distances, reached_counts)
        )
        positive_points = tuple(
            (item.distance, item.per_side_intensity_per_second.ln())
            for item in intensities
            if item.reached_trades > 0
        )
        intercept, slope, intensity_fit_r_squared = _linear_fit(positive_points)
        intensity_decay = -slope
        if intensity_decay <= 0:
            raise ValueError("fitted intensity does not decrease with quote distance")
        intensity_scale = intercept.exp()

    return ASCalibration(
        volatility_per_sqrt_second=volatility,
        intensity_decay=intensity_decay,
        intensity_scale_per_second=intensity_scale,
        intensity_fit_r_squared=intensity_fit_r_squared,
        active_exposure_seconds=exposure_seconds,
        variance_observations=variance_observations,
        active_trade_events=active_trades,
        distance_intensities=intensities,
        source_captures=tuple(sources),
    )


def write_calibration(calibration: ASCalibration, output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(
            json.dumps(calibration.report(), indent=2, sort_keys=True) + "\n"
        )
    return output


def load_calibration(path: str | Path) -> Mapping[str, Any]:
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read calibration: {exc}") from exc
    if report.get("calibration_schema_version") != CALIBRATION_SCHEMA_VERSION:
        raise ValueError("unsupported calibration schema version")
    sources = report.get("source_captures")
    if not isinstance(sources, list) or not sources:
        raise ValueError("calibration must identify at least one source capture")
    source_hashes: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not source.get("sha256"):
            raise ValueError("calibration contains an invalid source record")
        if source["sha256"] in source_hashes:
            raise ValueError("calibration contains duplicate source content")
        source_hashes.add(source["sha256"])
    _positive_decimal(report.get("volatility_per_sqrt_second"), "volatility")
    _positive_decimal(report.get("intensity_decay"), "intensity_decay")
    _positive_decimal(report.get("intensity_scale_per_second"), "intensity_scale")
    fit_r_squared = _finite_decimal(
        report.get("intensity_fit_r_squared"), "intensity_fit_r_squared"
    )
    if fit_r_squared < 0 or fit_r_squared > 1:
        raise ValueError("intensity_fit_r_squared must be between zero and one")
    return report


def _capture_statistics(
    path: Path, distances: tuple[Decimal, ...]
) -> _CaptureStatistics:
    book: L2Book | None = None
    decision_start_ns: int | None = None
    active = False
    last_event_ns: int | None = None
    last_mid: Decimal | None = None
    last_mid_ns: int | None = None
    squared_changes = variance_seconds = exposure_seconds = Decimal("0")
    variance_observations = active_trades = 0
    counts = [0 for _ in distances]

    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                record = json.loads(line)
                kind = record["kind"]
                payload = record["payload"]
                received = record["received_time_ns"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise SchemaError(
                    f"invalid capture record on line {line_number}"
                ) from exc

            if kind == "metadata":
                if book is not None:
                    raise SchemaError("capture contains multiple metadata records")
                book = L2Book(payload["venue"], payload["symbol"])
                continue
            if book is None:
                raise SchemaError(f"{kind} appears before metadata")
            if kind == "snapshot":
                book.load_snapshot(
                    parse_binance_snapshot(payload, book.symbol, received)
                )
                decision_start_ns = received
                active = False
                last_event_ns = last_mid_ns = None
                last_mid = None
                continue

            if (
                not active
                and decision_start_ns is not None
                and received >= decision_start_ns
                and book.synchronized
            ):
                active = True
                last_event_ns = decision_start_ns
                last_mid_ns = decision_start_ns
                last_mid = _mid(book)

            if kind == "delta":
                if active:
                    with localcontext(CALIBRATION_DECIMAL_CONTEXT):
                        exposure_seconds += _elapsed_seconds(last_event_ns, received)
                    last_event_ns = received
                status = book.apply_delta(parse_binance_delta(payload, received))
                if status is ApplyStatus.APPLIED and active:
                    mid = _mid(book)
                    if (
                        mid is not None
                        and last_mid is not None
                        and last_mid_ns is not None
                    ):
                        elapsed = _elapsed_seconds(last_mid_ns, received)
                        if elapsed > 0:
                            with localcontext(CALIBRATION_DECIMAL_CONTEXT):
                                squared_changes += (mid - last_mid) ** 2
                                variance_seconds += elapsed
                            variance_observations += 1
                    last_mid = mid
                    last_mid_ns = received
                elif status is ApplyStatus.GAP:
                    active = False
                    decision_start_ns = None
                    last_event_ns = last_mid_ns = None
                    last_mid = None
            elif kind == "trade":
                trade = parse_binance_trade(payload, received)
                if trade.symbol != book.symbol or trade.venue != book.venue:
                    raise SchemaError("trade identity does not match capture metadata")
                if not active:
                    continue
                with localcontext(CALIBRATION_DECIMAL_CONTEXT):
                    exposure_seconds += _elapsed_seconds(last_event_ns, received)
                last_event_ns = received
                mid = _mid(book)
                if mid is None:
                    continue
                active_trades += 1
                for index, distance in enumerate(distances):
                    with localcontext(CALIBRATION_DECIMAL_CONTEXT):
                        if trade.aggressor_side == "sell":
                            reached = trade.price <= mid - distance
                        else:
                            reached = trade.price >= mid + distance
                    counts[index] += int(reached)
            elif kind in {"gap", "trade_gap", "disconnect"}:
                if active:
                    with localcontext(CALIBRATION_DECIMAL_CONTEXT):
                        exposure_seconds += _elapsed_seconds(last_event_ns, received)
                active = False
                decision_start_ns = None
                last_event_ns = last_mid_ns = None
                last_mid = None
            else:
                raise SchemaError(
                    f"unsupported record kind on line {line_number}: {kind}"
                )

    return _CaptureStatistics(
        squared_changes,
        variance_seconds,
        variance_observations,
        exposure_seconds,
        active_trades,
        counts,
    )


def _elapsed_seconds(previous_ns: int | None, current_ns: int) -> Decimal:
    if previous_ns is None or current_ns < previous_ns:
        raise SchemaError("active local receive timestamps must be nondecreasing")
    with localcontext(CALIBRATION_DECIMAL_CONTEXT):
        return Decimal(current_ns - previous_ns) / Decimal("1000000000")


def _mid(book: L2Book) -> Decimal | None:
    if not book.synchronized or book.best_bid is None or book.best_ask is None:
        return None
    with localcontext(CALIBRATION_DECIMAL_CONTEXT):
        return (book.best_bid + book.best_ask) / Decimal("2")


def _linear_fit(
    points: tuple[tuple[Decimal, Decimal], ...]
) -> tuple[Decimal, Decimal, Decimal]:
    if len(points) < 2:
        raise ValueError("at least two distance bins need reached trades")
    with localcontext(CALIBRATION_DECIMAL_CONTEXT):
        count = Decimal(len(points))
        sum_x = sum((point[0] for point in points), Decimal("0"))
        sum_y = sum((point[1] for point in points), Decimal("0"))
        sum_xx = sum((point[0] ** 2 for point in points), Decimal("0"))
        sum_xy = sum((point[0] * point[1] for point in points), Decimal("0"))
        denominator = count * sum_xx - sum_x**2
        if denominator == 0:
            raise ValueError("distance bins do not identify an intensity slope")
        slope = (count * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / count
        residual_sum_squares = sum(
            ((y - (intercept + slope * x)) ** 2 for x, y in points),
            Decimal("0"),
        )
        mean_y = sum_y / count
        total_sum_squares = sum(
            ((y - mean_y) ** 2 for _, y in points), Decimal("0")
        )
        r_squared = (
            Decimal("1") - residual_sum_squares / total_sum_squares
            if total_sum_squares > 0
            else Decimal("0")
        )
    return intercept, slope, r_squared


def _positive_decimal(value: Any, field_name: str) -> Decimal:
    parsed = _finite_decimal(value, field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive and finite")
    return parsed


def _finite_decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed
