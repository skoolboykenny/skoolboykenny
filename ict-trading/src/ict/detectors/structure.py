"""Break of structure and market structure shift.

The two are easy to confuse and behave very differently, so they are separate
functions here.

A **break of structure** is continuation: price closes beyond the last swing in
the direction it was already going.

A **market structure shift** is reversal: after a liquidity sweep, price closes
beyond the last *opposing* swing, and does it with displacement. The sweep and
the displacement are both required. Without the sweep it is just a break in the
other direction; without displacement it is drift, and drift reverses back.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import DisplacementConfig, StructureConfig
from ._scan import NOT_FOUND, PriceScanner
from .displacement import displacement_mask
from .swings import find_swings, prominent

BOS_COLUMNS = ("time", "direction", "level", "swing_time")
MSS_COLUMNS = ("time", "direction", "level", "swing_time", "sweep_time", "sweep_side")


def _empty(columns: tuple[str, ...]) -> pd.DataFrame:
    dtypes = {
        "time": "datetime64[ns, UTC]",
        "swing_time": "datetime64[ns, UTC]",
        "sweep_time": "datetime64[ns, UTC]",
        "direction": "object",
        "sweep_side": "object",
        "level": "float64",
    }
    return pd.DataFrame({c: pd.Series(dtype=dtypes[c]) for c in columns})


def find_breaks_of_structure(
    candles: pd.DataFrame,
    swings: pd.DataFrame | None = None,
    config: StructureConfig | None = None,
) -> pd.DataFrame:
    """Detect closes beyond the most recently confirmed structure point.

    Each swing can only be broken once; after that it is history and the next
    swing takes over as the level to watch.

    Only prominent swings count. Treating every two bar fractal as structure
    makes a break of structure almost meaningless, because nearly every swing
    is eventually closed beyond.
    """
    config = config or StructureConfig()
    if swings is None:
        swings = find_swings(candles)
    swings = prominent(candles, swings, config.prominence_lookback)
    if swings.empty or candles.empty:
        return _empty(BOS_COLUMNS)

    scanner = PriceScanner(
        candles["high"].to_numpy(),
        candles["low"].to_numpy(),
        candles["close"].to_numpy(),
    )
    index = candles.index

    rows = []
    for kind, direction in (("high", "up"), ("low", "down")):
        selected = swings.loc[swings["kind"] == kind]
        if selected.empty:
            continue
        starts = index.searchsorted(selected["confirmed_at"].to_numpy(), side="right")
        first_beyond = (
            scanner.first_close_above if direction == "up" else scanner.first_close_below
        )

        for start, level, swing_time in zip(
            starts, selected["price"].to_numpy(), selected["time"].to_numpy()
        ):
            hit = first_beyond(int(start), float(level))
            if hit == NOT_FOUND:
                continue
            rows.append(
                {
                    "time": index[hit],
                    "direction": direction,
                    "level": float(level),
                    "swing_time": swing_time,
                }
            )

    if not rows:
        return _empty(BOS_COLUMNS)
    return (
        pd.DataFrame(rows).sort_values("time").reset_index(drop=True)[list(BOS_COLUMNS)]
    )


def find_market_structure_shifts(
    candles: pd.DataFrame,
    sweeps: pd.DataFrame,
    swings: pd.DataFrame | None = None,
    config: StructureConfig | None = None,
    displacement: DisplacementConfig | None = None,
) -> pd.DataFrame:
    """Detect market structure shifts: sweep, then displaced close beyond the
    last opposing swing.

    A sweep of sell side liquidity (a low taken) can only produce an upward
    shift, and vice versa, because the shift has to point away from where the
    stops were taken.
    """
    config = config or StructureConfig()
    displacement = displacement or DisplacementConfig()
    if swings is None:
        swings = find_swings(candles)
    # The level a shift breaks has to stand out, but less than a break of
    # structure does: a shift reverses a trend against the last opposing short
    # term swing rather than confirming it against a major one.
    swings = prominent(candles, swings, config.mss_prominence_lookback)
    if sweeps.empty or swings.empty or candles.empty:
        return _empty(MSS_COLUMNS)

    displaces = displacement_mask(candles, displacement).to_numpy()
    # Running total, so "did anything in this leg displace" is two lookups.
    displaced_by = np.concatenate([[0], np.cumsum(displaces)])
    closes = candles["close"].to_numpy()
    index = candles.index

    # Each kind of swing, sorted by when it became known, so the last one
    # standing before a sweep is a binary search rather than a scan.
    by_kind = {}
    for kind in ("high", "low"):
        selected = swings.loc[swings["kind"] == kind].sort_values("confirmed_at")
        by_kind[kind] = (
            selected["confirmed_at"].to_numpy(),
            selected["price"].to_numpy(),
            selected["time"].to_numpy(),
        )

    sweep_positions = index.searchsorted(sweeps["time"].to_numpy(), side="left")
    rows = []

    for start, sweep_time, side in zip(
        sweep_positions, sweeps["time"].to_numpy(), sweeps["side"].to_numpy()
    ):
        # A low swept (sell side) turns the market up, and the level to break
        # is the last swing high standing before the sweep.
        direction, kind = ("up", "high") if side == "sell" else ("down", "low")
        confirmed, prices, times = by_kind[kind]
        standing = np.searchsorted(confirmed, sweep_time, side="right")
        if standing == 0:
            continue
        level = float(prices[standing - 1])
        swing_time = times[standing - 1]

        begin = int(start) + 1
        end = min(begin + config.sweep_lookback, len(index))
        if begin >= end:
            continue

        segment = closes[begin:end]
        broken = segment > level if direction == "up" else segment < level

        if config.displacement_in_leg:
            # The leg runs from the sweep to the candle that breaks. It counts
            # if anything in it displaced, not only the breaking candle.
            candidates = begin + np.flatnonzero(broken)
            leg_start = int(start)
            hits = [
                i
                for i in candidates
                if displaced_by[i + 1] - displaced_by[leg_start] > 0
            ]
            hits = np.array(hits, dtype=int) - begin
        else:
            hits = np.flatnonzero(broken & displaces[begin:end])

        if not len(hits):
            continue

        rows.append(
            {
                "time": index[begin + int(hits[0])],
                "direction": direction,
                "level": level,
                "swing_time": swing_time,
                "sweep_time": sweep_time,
                "sweep_side": side,
            }
        )

    if not rows:
        return _empty(MSS_COLUMNS)
    return (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["time", "direction"])
        .sort_values("time")
        .reset_index(drop=True)[list(MSS_COLUMNS)]
    )
