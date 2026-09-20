"""Helpers for building tiny candle sequences with known answers.

Every detector test is built from a handful of candles written out by hand, so
the expected result can be reasoned about on paper rather than trusted because
the code produced it.
"""

from __future__ import annotations

import pandas as pd
import pytest


def make_candles(
    rows: list[tuple[float, float, float, float]],
    start: str = "2024-03-04 08:00",
    freq: str = "1min",
    tz: str = "UTC",
    volume: float = 100.0,
) -> pd.DataFrame:
    """Build a candle frame from ``(open, high, low, close)`` tuples."""
    index = pd.date_range(pd.Timestamp(start, tz=tz), periods=len(rows), freq=freq)
    frame = pd.DataFrame(
        rows, columns=["open", "high", "low", "close"], index=index.rename("timestamp")
    )
    frame["volume"] = volume
    return frame.astype("float64")


def flat(
    count: int, price: float = 100.0, start: str = "2024-03-04 08:00"
) -> pd.DataFrame:
    """A run of identical, boring candles, used as padding around a setup."""
    row = (price, price + 0.05, price - 0.05, price)
    return make_candles([row] * count, start=start)


@pytest.fixture
def candles_factory():
    return make_candles
