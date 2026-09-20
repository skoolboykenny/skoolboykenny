"""Average true range, the yardstick every size threshold is measured in.

Thresholds are expressed as ATR multiples rather than pips so the same config
works on EUR/USD and on NQ, and so a detector behaves the same in a quiet Asian
range as in a volatile New York open.
"""

from __future__ import annotations

import pandas as pd


def true_range(candles: pd.DataFrame) -> pd.Series:
    """True range per candle: the widest of the three classic spans."""
    previous_close = candles["close"].shift(1)
    spans = pd.concat(
        [
            candles["high"] - candles["low"],
            (candles["high"] - previous_close).abs(),
            (candles["low"] - previous_close).abs(),
        ],
        axis=1,
    )
    return spans.max(axis=1)


def atr(candles: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's ATR.

    The value at candle ``i`` uses candles up to and including ``i``, so a
    caller comparing candle ``i``'s body against ``atr.iloc[i]`` is comparing
    it against a window that includes itself. Where that matters, use
    :func:`atr_prior`.
    """
    if period < 1:
        raise ValueError("period must be at least 1")
    return true_range(candles).ewm(alpha=1 / period, adjust=False).mean()


def atr_prior(candles: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR as it stood *before* each candle, for thresholds that judge a candle.

    A displacement candle is large relative to what came before it. Measuring
    it against an ATR that already contains its own outsized range would damp
    exactly the signal being looked for.
    """
    return atr(candles, period).shift(1)
