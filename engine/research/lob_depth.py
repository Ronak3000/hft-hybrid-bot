"""Leakage-safe multi-level order-book windows from verified raw captures."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import numpy as np

from engine.market_data import verify_capture
from .l2_features import _iter_l2_depth_verified


@dataclass(frozen=True, slots=True)
class DepthSession:
    path: Path
    source_sha256: str
    venue: str
    symbol: str
    levels: int
    first_receive_ns: int
    last_receive_ns: int
    receive_ns: tuple[int, ...]
    groups: tuple[int, ...]
    mids: tuple[Decimal, ...]
    ladders: np.ndarray


def load_depth_session(path: Path, levels: int = 10) -> DepthSession:
    if levels < 2:
        raise ValueError("depth models require at least two levels per side")
    manifest = verify_capture(path)
    times, groups, mids, ladders = [], [], [], []
    previous_segment, previous_time = None, -1
    previous_ordinal = -1
    group = -1
    first_time = None
    for row, bids, asks, ordinal in _iter_l2_depth_verified(path, levels):
        if row.received_time_ns < previous_time:
            raise ValueError(f"{path.name}: depth receive times go backwards")
        previous_time = row.received_time_ns
        if first_time is None:
            first_time = previous_time
        if len(bids) != levels or len(asks) != levels:
            # Do not zero-pad missing depth or bridge a shallow interval.
            previous_segment = None
            continue
        if previous_segment != row.segment_id or ordinal != previous_ordinal + 1:
            group += 1
            previous_segment = row.segment_id
        previous_ordinal = ordinal
        times.append(previous_time)
        groups.append(group)
        mids.append(row.mid_price)
        ladders.append([float(value) for (bid, bsize), (ask, asize) in zip(bids, asks, strict=True)
                        for value in (bid, bsize, ask, asize)])
    if not times:
        raise ValueError(f"{path.name}: no full-depth L2 observations")
    array = np.asarray(ladders, dtype=np.float64)
    if not np.isfinite(array).all():
        raise ValueError(f"{path.name}: non-finite order-book values")
    metadata = manifest["metadata"]
    return DepthSession(path, manifest["sha256"], metadata["venue"], metadata["symbol"], levels,
                        first_time, previous_time, tuple(times), tuple(groups), tuple(mids), array)


def validate_depth_splits(splits: dict[str, list[DepthSession]]) -> None:
    seen, markets = set(), set()
    end = -1
    for key in ("train", "validation", "test"):
        if not splits.get(key):
            raise ValueError(f"{key}: supply at least one capture")
        for session in splits[key]:
            if session.source_sha256 in seen:
                raise ValueError("a raw capture was reused")
            if session.first_receive_ns <= end:
                raise ValueError("captures overlap or are not in chronological receive-time order")
            seen.add(session.source_sha256)
            markets.add((session.venue, session.symbol, session.levels))
            end = session.last_receive_ns
    if len(markets) != 1:
        raise ValueError("all splits must use the same venue, symbol, and depth")


class DepthWindows:
    """Index-only windows: normalize lazily instead of materializing every overlap."""

    def __init__(self, sessions: list[DepthSession], lookback: int, horizon: int) -> None:
        if lookback < 2 or horizon < 1:
            raise ValueError("lookback must be >= 2 and horizon must be positive")
        self.sessions, self.lookback, self.horizon = sessions, lookback, horizon
        self.items: list[tuple[int, int, int]] = []
        for session_index, session in enumerate(sessions):
            old_size = len(self.items)
            for end in range(lookback - 1, len(session.groups) - horizon):
                first, target = end - lookback + 1, end + horizon
                if session.groups[first] != session.groups[target]:
                    continue
                now, future = session.mids[end], session.mids[target]
                self.items.append((session_index, end, 1 + int(future > now) - int(future < now)))
            if len(self.items) == old_size:
                raise ValueError(f"{session.path.name}: no complete window at horizon {horizon}")

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> tuple[np.ndarray, int]:
        session_index, end, label = self.items[index]
        session = self.sessions[session_index]
        start = end - self.lookback + 1
        window = session.ladders[start:end + 1].copy()
        mid = float(session.mids[start])
        # Anchor to a value already known at the start of this window; no fitted
        # global scaler, and historical price movement within the window survives.
        window[:, ::2] = (window[:, ::2] / mid - 1) * 10_000
        window[:, 1::2] = np.log1p(window[:, 1::2])
        return window.astype(np.float32), label
