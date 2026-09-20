"""Swing highs and lows: the fractal points everything else is anchored to.

A swing high at candle ``i`` is a high strictly greater than the highs of the
``n`` candles either side. Ties do not count, which keeps flat, ranging price
from producing a swing on every candle.

A swing is only *confirmed* ``n`` candles after it forms, because that is when
the right-hand side exists. The confirmation time is recorded separately from
the swing time, and a caller running bar by bar must filter on
``confirmed_at``: using a swing before its right side closed is lookahead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import SwingConfig

SWING_COLUMNS = ("time", "price", "kind", "confirmed_at")


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.Series(dtype="datetime64[ns, UTC]"),
            "price": pd.Series(dtype="float64"),
            "kind": pd.Series(dtype="object"),
            "confirmed_at": pd.Series(dtype="datetime64[ns, UTC]"),
        }
    )


def find_swings(
    candles: pd.DataFrame, config: SwingConfig | None = None
) -> pd.DataFrame:
    """Detect swing highs and lows.

    Returns one row per swing with columns ``time``, ``price``, ``kind``
    (``"high"`` or ``"low"``) and ``confirmed_at``, sorted by time.
    """
    config = config or SwingConfig()
    n = config.n
    if n < 1:
        raise ValueError("swing n must be at least 1")
    if len(candles) < 2 * n + 1:
        return _empty()

    highs = candles["high"].to_numpy()
    lows = candles["low"].to_numpy()
    index = candles.index

    is_high = np.ones(len(candles), dtype=bool)
    is_low = np.ones(len(candles), dtype=bool)
    is_high[:n] = is_high[-n:] = False
    is_low[:n] = is_low[-n:] = False

    for offset in range(1, n + 1):
        left_high = np.roll(highs, offset)
        right_high = np.roll(highs, -offset)
        is_high &= (highs > left_high) & (highs > right_high)

        left_low = np.roll(lows, offset)
        right_low = np.roll(lows, -offset)
        is_low &= (lows < left_low) & (lows < right_low)

    rows = []
    for positions, kind, prices in ((is_high, "high", highs), (is_low, "low", lows)):
        for position in np.flatnonzero(positions):
            rows.append(
                {
                    "time": index[position],
                    "price": float(prices[position]),
                    "kind": kind,
                    "confirmed_at": index[position + n],
                }
            )

    if not rows:
        return _empty()
    return (
        pd.DataFrame(rows)
        .sort_values(["time", "kind"])
        .reset_index(drop=True)[list(SWING_COLUMNS)]
    )


def confirmed_by(swings: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """The swings whose right-hand side had closed by ``now``."""
    if swings.empty:
        return swings
    return swings.loc[swings["confirmed_at"] <= pd.Timestamp(now)].reset_index(
        drop=True
    )


def last_swing(swings: pd.DataFrame, kind: str) -> pd.Series | None:
    """The most recent swing of ``kind``, or ``None``."""
    matching = swings.loc[swings["kind"] == kind]
    if matching.empty:
        return None
    return matching.iloc[-1]
