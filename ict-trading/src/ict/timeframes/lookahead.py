"""The lookahead guard.

Lookahead is the main source of false ICT backtest results: a 4h bias computed
from a 4h candle that had not yet closed is a bias computed from the future.
Every detector and, later, every strategy reads higher timeframe data through
this module and never touches a raw frame directly.

The rule is one line: a candle whose open time is ``T`` on a timeframe of
duration ``D`` is usable at ``now`` only when ``T + D <= now``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .resample import TIMEFRAMES, build_stack, timeframe_delta


def closed_candles(
    candles: pd.DataFrame, timeframe: str, now: pd.Timestamp
) -> pd.DataFrame:
    """Return only the candles of ``timeframe`` fully closed at ``now``.

    ``now`` is a 1 minute timestamp, the moment the engine is making a
    decision. The returned frame is safe to hand to any detector.
    """
    now = pd.Timestamp(now)
    if now.tz is None:
        raise ValueError("`now` must be timezone aware")
    delta = timeframe_delta(timeframe)
    return candles.loc[candles.index + delta <= now]


def last_closed(
    candles: pd.DataFrame, timeframe: str, now: pd.Timestamp
) -> pd.Series | None:
    """The most recent fully closed candle of ``timeframe`` at ``now``."""
    closed = closed_candles(candles, timeframe, now)
    if closed.empty:
        return None
    return closed.iloc[-1]


def knowable_at(
    events: pd.DataFrame,
    timeframe: str,
    now: pd.Timestamp,
    column: str = "time",
) -> pd.DataFrame:
    """Events from ``timeframe`` that could already be known at ``now``.

    Running a detector over a whole series and then filtering is far cheaper
    than re-running it on a truncated series at every bar, but it is only
    equivalent if the filter is right. An event timed at candle ``X`` on a 15
    minute timeframe is not knowable at ``X``: that candle is still forming.
    It becomes knowable when the candle closes, at ``X + 15m``.

    Use this for any detector output whose fields look backward only. Fields
    computed from later data, such as a pool's ``swept_at`` or a gap's
    ``mitigated_at``, are not made safe by this filter, and have their own
    point in time accessors (:func:`~ict.detectors.liquidity.unswept`,
    :func:`~ict.detectors.fvg.unmitigated`).
    """
    if events.empty:
        return events
    now = pd.Timestamp(now)
    if now.tz is None:
        raise ValueError("`now` must be timezone aware")
    closes = pd.DatetimeIndex(events[column]) + timeframe_delta(timeframe)
    return events.loc[closes <= now]


@dataclass
class TimeframeStack:
    """A 4h/1h/15m/1m stack that can only ever be read as at a point in time.

    Build it once per instrument, then call :meth:`as_of` on each 1 minute
    candle. There is deliberately no accessor that returns a whole frame: if a
    caller wants candles, it has to say when it is standing.
    """

    frames: dict[str, pd.DataFrame]

    @classmethod
    def from_minutes(cls, candles: pd.DataFrame) -> "TimeframeStack":
        return cls(frames=build_stack(candles))

    @property
    def timeframes(self) -> tuple[str, ...]:
        return TIMEFRAMES

    def as_of(self, now: pd.Timestamp, timeframe: str) -> pd.DataFrame:
        """Candles of ``timeframe`` that are fully closed at ``now``."""
        if timeframe not in self.frames:
            raise KeyError(f"timeframe not in stack: {timeframe!r}")
        return closed_candles(self.frames[timeframe], timeframe, now)

    def snapshot(self, now: pd.Timestamp) -> dict[str, pd.DataFrame]:
        """The whole stack as at ``now``, every frame lookahead safe."""
        return {tf: self.as_of(now, tf) for tf in self.frames}
