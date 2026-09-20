"""Build 15m, 1h and 4h candles from 1 minute data, aligned to New York time.

Alignment matters: a 4h candle that starts at 00:00 New York is a different
candle from one that starts at 00:00 UTC, and ICT's day begins at the New York
midnight open. So resampling happens on a New York index and the result is
converted back to UTC for storage.
"""

from __future__ import annotations

import pandas as pd

from ..config import MARKET_TZ, OHLC_COLUMNS, STORAGE_TZ

#: Timeframes the stack is built from, coarsest first.
TIMEFRAMES: tuple[str, ...] = ("4h", "1h", "15m", "1m")

_PANDAS_RULE = {"15m": "15min", "1h": "1h", "4h": "4h"}

_AGGREGATION = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def resample(candles: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample 1 minute candles to ``timeframe``, aligned to New York time.

    Empty periods (weekends, holidays, feed gaps) are dropped rather than
    forward filled: a candle that did not trade is not a candle, and inventing
    one would give detectors phantom structure.
    """
    if timeframe == "1m":
        return candles.copy()
    if timeframe not in _PANDAS_RULE:
        raise ValueError(f"unsupported timeframe: {timeframe!r}")

    ny = candles.tz_convert(MARKET_TZ)
    out = ny.resample(_PANDAS_RULE[timeframe], label="left", closed="left").agg(
        _AGGREGATION
    )
    out = out.dropna(subset=["open"])
    out = out.tz_convert(STORAGE_TZ)
    out.index.name = candles.index.name
    return out[list(OHLC_COLUMNS)]


def build_stack(candles: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build every timeframe in :data:`TIMEFRAMES` from 1 minute candles."""
    return {tf: resample(candles, tf) for tf in TIMEFRAMES}


def timeframe_delta(timeframe: str) -> pd.Timedelta:
    """The duration of one candle on ``timeframe``."""
    if timeframe == "1m":
        return pd.Timedelta(minutes=1)
    return pd.Timedelta(_PANDAS_RULE[timeframe])
