"""New York time, sessions and kill zones.

Timestamps are stored in UTC everywhere. The market's day, its sessions and its
kill zones are defined in New York time, which observes daylight saving, so the
offset is never hard coded: it is always derived by converting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from ..config import MARKET_TZ, STORAGE_TZ


@dataclass(frozen=True)
class Window:
    """A named span of the New York clock.

    ``start`` may be later than ``end``, which means the window crosses
    midnight (the Asian range does).
    """

    name: str
    start: time
    end: time

    @property
    def crosses_midnight(self) -> bool:
        return self.start > self.end


#: Kill zones and reference windows, in New York time.
KILL_ZONES: tuple[Window, ...] = (
    Window("asian_range", time(20, 0), time(0, 0)),
    Window("london", time(2, 0), time(5, 0)),
    Window("london_silver_bullet", time(3, 0), time(4, 0)),
    Window("ny_am", time(7, 0), time(10, 0)),
    Window("ny_am_silver_bullet", time(10, 0), time(11, 0)),
    Window("london_close", time(10, 0), time(12, 0)),
    Window("ny_pm_silver_bullet", time(14, 0), time(15, 0)),
)

SILVER_BULLET_WINDOWS: tuple[str, ...] = (
    "london_silver_bullet",
    "ny_am_silver_bullet",
    "ny_pm_silver_bullet",
)

#: The daily reference level ICT anchors the day to.
MIDNIGHT_OPEN = time(0, 0)


def to_market_tz(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Convert a UTC index to New York time, DST aware."""
    if index.tz is None:
        index = index.tz_localize(STORAGE_TZ)
    return index.tz_convert(MARKET_TZ)


def to_storage_tz(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Convert any tz-aware index back to UTC."""
    if index.tz is None:
        raise ValueError("index must be timezone aware before converting to UTC")
    return index.tz_convert(STORAGE_TZ)


def window_by_name(name: str) -> Window:
    for window in KILL_ZONES:
        if window.name == name:
            return window
    raise KeyError(f"unknown kill zone: {name!r}")


def in_window(index: pd.DatetimeIndex, window: Window) -> pd.Series:
    """Boolean mask: which timestamps fall inside ``window``.

    The window is half open, ``[start, end)``, so back to back windows do not
    both claim the boundary candle.
    """
    ny = to_market_tz(index)
    minutes = ny.hour * 60 + ny.minute
    start = window.start.hour * 60 + window.start.minute
    end = window.end.hour * 60 + window.end.minute

    if window.crosses_midnight:
        # Midnight itself terminates the Asian range, so 00:00 is excluded by
        # the half open rule on both halves of the span.
        mask = (minutes >= start) | (minutes < end) if end else (minutes >= start)
    else:
        mask = (minutes >= start) & (minutes < end)

    return pd.Series(mask, index=index, name=window.name)


def kill_zone_of(index: pd.DatetimeIndex) -> pd.Series:
    """Label each timestamp with the kill zone it falls in, or an empty string.

    Windows overlap: the NY AM Silver Bullet hour sits inside both NY AM and
    London close, and the London Silver Bullet hour sits inside London. The
    narrower Silver Bullet label is the useful one, so those are claimed first.
    """
    ordered = tuple(w for w in KILL_ZONES if w.name in SILVER_BULLET_WINDOWS) + tuple(
        w for w in KILL_ZONES if w.name not in SILVER_BULLET_WINDOWS
    )
    labels = pd.Series("", index=index, dtype="object")
    for window in ordered:
        mask = in_window(index, window).to_numpy()
        unclaimed = (labels == "").to_numpy()
        labels[mask & unclaimed] = window.name
    return labels


def market_date(index: pd.DatetimeIndex) -> pd.Series:
    """The New York calendar date each timestamp belongs to."""
    ny = to_market_tz(index)
    return pd.Series(ny.date, index=index, name="market_date")


def is_silver_bullet(index: pd.DatetimeIndex) -> pd.Series:
    """Whether each timestamp falls in one of the three Silver Bullet hours."""
    mask = pd.Series(False, index=index)
    for name in SILVER_BULLET_WINDOWS:
        mask |= in_window(index, window_by_name(name))
    return mask
