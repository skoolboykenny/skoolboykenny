"""Fair value gaps, with mitigation tracking.

Three candles. A bullish gap exists when candle 1's high is below candle 3's
low: price moved so fast that the middle candle's range was never offered on
both sides. The gap is the span between those two prices.

Mitigation is tracked because an FVG's usefulness is spent once price has
traded back into it. Two marks are recorded: ``mitigated_at``, the first touch
of the gap, and ``inverted_at``, the point where price closed clean through it.
An inverted FVG is the same zone read with the opposite polarity, which is why
it is worth keeping rather than deleting.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import FVGConfig
from ._scan import NOT_FOUND, PriceScanner
from .atr import atr

FVG_COLUMNS = (
    "time",
    "direction",
    "top",
    "bottom",
    "size",
    "mitigated_at",
    "inverted_at",
)


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.Series(dtype="datetime64[ns, UTC]"),
            "direction": pd.Series(dtype="object"),
            "top": pd.Series(dtype="float64"),
            "bottom": pd.Series(dtype="float64"),
            "size": pd.Series(dtype="float64"),
            "mitigated_at": pd.Series(dtype="datetime64[ns, UTC]"),
            "inverted_at": pd.Series(dtype="datetime64[ns, UTC]"),
        }
    )


def find_fvgs(candles: pd.DataFrame, config: FVGConfig | None = None) -> pd.DataFrame:
    """Detect fair value gaps and track how each one was later used.

    The gap is timed at the third candle, because that is when it exists and
    can be acted on. Timing it at the middle candle would be lookahead.
    """
    config = config or FVGConfig()
    if len(candles) < 3:
        return _empty()

    highs = candles["high"].to_numpy()
    lows = candles["low"].to_numpy()
    index = candles.index
    reference = atr(candles, config.atr_period).to_numpy()

    first_high, first_low = highs[:-2], lows[:-2]
    third_high, third_low = highs[2:], lows[2:]
    third_time = index[2:]
    third_atr = reference[2:]

    minimum = third_atr * config.min_gap_atr

    bullish = (third_low - first_high) > np.maximum(minimum, 0.0)
    bearish = (first_low - third_high) > np.maximum(minimum, 0.0)

    rows = []
    for position in np.flatnonzero(bullish):
        rows.append(
            {
                "time": third_time[position],
                "direction": "bullish",
                "top": float(third_low[position]),
                "bottom": float(first_high[position]),
            }
        )
    for position in np.flatnonzero(bearish):
        rows.append(
            {
                "time": third_time[position],
                "direction": "bearish",
                "top": float(first_low[position]),
                "bottom": float(third_high[position]),
            }
        )

    if not rows:
        return _empty()

    gaps = pd.DataFrame(rows)
    gaps["size"] = gaps["top"] - gaps["bottom"]
    mitigated, inverted = _track_usage(candles, gaps)
    gaps["mitigated_at"] = mitigated
    gaps["inverted_at"] = inverted
    return gaps.sort_values("time").reset_index(drop=True)[list(FVG_COLUMNS)]


def _track_usage(
    candles: pd.DataFrame, gaps: pd.DataFrame
) -> tuple[pd.Series, pd.Series]:
    """First touch of each gap, and the close that inverted it."""
    scanner = PriceScanner(
        candles["high"].to_numpy(),
        candles["low"].to_numpy(),
        candles["close"].to_numpy(),
    )
    index = candles.index
    starts = index.searchsorted(gaps["time"].to_numpy(), side="right")

    mitigated: list[pd.Timestamp] = []
    inverted: list[pd.Timestamp] = []

    for start, top, bottom, direction in zip(
        starts,
        gaps["top"].to_numpy(),
        gaps["bottom"].to_numpy(),
        gaps["direction"].to_numpy(),
    ):
        start = int(start)
        touch = scanner.first_overlap(start, float(bottom), float(top))
        mitigated.append(index[touch] if touch != NOT_FOUND else pd.NaT)

        # Inversion is a close clean through the far side of the gap.
        through = (
            scanner.first_close_below(start, float(bottom))
            if direction == "bullish"
            else scanner.first_close_above(start, float(top))
        )
        inverted.append(index[through] if through != NOT_FOUND else pd.NaT)

    return (
        pd.Series(mitigated, index=gaps.index, dtype="datetime64[ns, UTC]"),
        pd.Series(inverted, index=gaps.index, dtype="datetime64[ns, UTC]"),
    )


def unmitigated(gaps: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Gaps that exist at ``now`` and have not been traded back into."""
    now = pd.Timestamp(now)
    if gaps.empty:
        return gaps
    existing = gaps["time"] <= now
    intact = gaps["mitigated_at"].isna() | (gaps["mitigated_at"] > now)
    return gaps.loc[existing & intact].reset_index(drop=True)
