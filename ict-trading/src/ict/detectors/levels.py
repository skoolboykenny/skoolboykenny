"""Session levels: the reference prices a day is traded against.

These are not detected so much as read off the clock: the Asian range, the
previous day's and week's extremes, and the midnight open. They are the levels
the higher timeframe draw is usually one of, and the levels a Judas swing runs
before reversing.
"""

from __future__ import annotations

import pandas as pd

from ..timeframes.sessions import MIDNIGHT_OPEN, in_window, market_date, window_by_name

LEVEL_COLUMNS = ("market_date", "name", "price", "available_from")


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "market_date": pd.Series(dtype="object"),
            "name": pd.Series(dtype="object"),
            "price": pd.Series(dtype="float64"),
            "available_from": pd.Series(dtype="datetime64[ns, UTC]"),
        }
    )


def session_levels(candles: pd.DataFrame) -> pd.DataFrame:
    """Compute the session levels for every New York day in ``candles``.

    ``available_from`` is the moment the level is finished and safe to use. The
    Asian range is not a level until the Asian session has closed, and the
    previous day's high is not available until that day has ended. A caller
    must filter on it.
    """
    if candles.empty:
        return _empty()

    dates = market_date(candles.index)
    asian = in_window(candles.index, window_by_name("asian_range"))

    rows: list[dict] = []
    daily_high: dict[object, float] = {}
    daily_low: dict[object, float] = {}

    for day, group in candles.groupby(dates.to_numpy(), sort=True):
        daily_high[day] = float(group["high"].max())
        daily_low[day] = float(group["low"].min())

        # Midnight open: the open of the first candle of the New York day.
        first = group.index[0]
        ny_first = first.tz_convert("America/New_York")
        if (ny_first.hour, ny_first.minute) <= (MIDNIGHT_OPEN.hour, 5):
            rows.append(
                {
                    "market_date": day,
                    "name": "midnight_open",
                    "price": float(group["open"].iloc[0]),
                    "available_from": first,
                }
            )

        # The Asian range that belongs to this day ran the evening before, so
        # it is selected by window rather than by date.
        window = group.loc[asian.loc[group.index].to_numpy()]
        if not window.empty:
            close = window.index[-1]
            rows.append(
                {
                    "market_date": day,
                    "name": "asian_high",
                    "price": float(window["high"].max()),
                    "available_from": close,
                }
            )
            rows.append(
                {
                    "market_date": day,
                    "name": "asian_low",
                    "price": float(window["low"].min()),
                    "available_from": close,
                }
            )

    days = sorted(daily_high)
    for previous, day in zip(days, days[1:]):
        start = candles.index[dates.to_numpy() == day][0]
        rows.append(
            {
                "market_date": day,
                "name": "previous_day_high",
                "price": daily_high[previous],
                "available_from": start,
            }
        )
        rows.append(
            {
                "market_date": day,
                "name": "previous_day_low",
                "price": daily_low[previous],
                "available_from": start,
            }
        )

    if not rows:
        return _empty()
    return (
        pd.DataFrame(rows)
        .sort_values(["market_date", "name"])
        .reset_index(drop=True)[list(LEVEL_COLUMNS)]
    )


def available_at(levels: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """The levels that are finished and usable at ``now``."""
    if levels.empty:
        return levels
    return levels.loc[levels["available_from"] <= pd.Timestamp(now)].reset_index(
        drop=True
    )
