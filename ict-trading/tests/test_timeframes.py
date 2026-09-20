import pandas as pd
import pytest

from ict.timeframes.lookahead import TimeframeStack, closed_candles, last_closed
from ict.timeframes.resample import build_stack, resample, timeframe_delta
from ict.timeframes.sessions import (
    in_window,
    is_silver_bullet,
    kill_zone_of,
    to_market_tz,
    window_by_name,
)


def minutes(hours: int = 24, start: str = "2024-03-04 00:00") -> pd.DataFrame:
    """A run of 1 minute candles starting at a New York wall clock time."""
    index = pd.date_range(
        pd.Timestamp(start, tz="America/New_York").tz_convert("UTC"),
        periods=hours * 60,
        freq="1min",
    )
    return pd.DataFrame(
        {
            "open": 1.0,
            "high": 1.5,
            "low": 0.5,
            "close": 1.2,
            "volume": 10.0,
        },
        index=index.rename("timestamp"),
    )


def test_resampling_aligns_to_new_york_midnight():
    candles = minutes(24)
    four_hour = resample(candles, "4h")
    first = to_market_tz(four_hour.index)[0]

    assert (first.hour, first.minute) == (0, 0)
    assert len(four_hour) == 6


def test_resampled_candle_aggregates_correctly():
    candles = minutes(1)
    candles.iloc[0, candles.columns.get_loc("open")] = 5.0
    candles.iloc[10, candles.columns.get_loc("high")] = 9.0
    candles.iloc[20, candles.columns.get_loc("low")] = 0.1
    candles.iloc[-1, candles.columns.get_loc("close")] = 7.0

    hour = resample(candles, "1h").iloc[0]

    assert hour["open"] == 5.0
    assert hour["high"] == 9.0
    assert hour["low"] == 0.1
    assert hour["close"] == 7.0
    assert hour["volume"] == 60 * 10.0


def test_empty_periods_are_dropped_not_filled():
    candles = pd.concat([minutes(1), minutes(1, start="2024-03-04 06:00")])
    hours = resample(candles, "1h")

    # Two traded hours, and no invented candles for the four in between.
    assert len(hours) == 2


def test_stack_has_every_timeframe():
    stack = build_stack(minutes(24))
    assert set(stack) == {"1m", "15m", "1h", "4h"}
    assert len(stack["15m"]) == 96


def test_closed_candles_excludes_the_forming_one():
    candles = minutes(24)
    four_hour = resample(candles, "4h")

    # The 04:00 New York candle closes at 08:00. At 07:59 it is still forming.
    opens = to_market_tz(four_hour.index)
    at_0759 = pd.Timestamp("2024-03-04 07:59", tz="America/New_York")
    visible = closed_candles(four_hour, "4h", at_0759)

    assert len(visible) == 1
    assert to_market_tz(visible.index)[-1].hour == 0
    assert opens[1].hour == 4


def test_closed_candles_includes_it_the_moment_it_closes():
    candles = minutes(24)
    four_hour = resample(candles, "4h")
    at_0800 = pd.Timestamp("2024-03-04 08:00", tz="America/New_York")

    visible = closed_candles(four_hour, "4h", at_0800)
    assert to_market_tz(visible.index)[-1].hour == 4


def test_last_closed_returns_none_before_any_candle_has_closed():
    candles = minutes(24)
    four_hour = resample(candles, "4h")
    at_0001 = pd.Timestamp("2024-03-04 00:01", tz="America/New_York")

    assert last_closed(four_hour, "4h", at_0001) is None


def test_stack_as_of_is_lookahead_safe_on_every_timeframe():
    stack = TimeframeStack.from_minutes(minutes(24))
    now = pd.Timestamp("2024-03-04 09:30", tz="America/New_York")

    for timeframe, frame in stack.snapshot(now).items():
        if frame.empty:
            continue
        latest_close = frame.index[-1] + timeframe_delta(timeframe)
        assert latest_close <= now, f"{timeframe} leaked a candle from the future"


def test_naive_now_is_rejected():
    stack = TimeframeStack.from_minutes(minutes(2))
    with pytest.raises(ValueError):
        stack.as_of(pd.Timestamp("2024-03-04 09:30"), "1m")


def test_kill_zones_are_labelled_in_new_york_time():
    candles = minutes(24)
    labels = kill_zone_of(candles.index)
    ny = to_market_tz(candles.index)

    at_0830 = labels[(ny.hour == 8) & (ny.minute == 30)]
    at_0330 = labels[(ny.hour == 3) & (ny.minute == 30)]
    at_1330 = labels[(ny.hour == 13) & (ny.minute == 30)]

    assert at_0830.iloc[0] == "ny_am"
    assert at_0330.iloc[0] == "london_silver_bullet"
    assert at_1330.iloc[0] == ""


def test_silver_bullet_covers_the_three_hours():
    candles = minutes(24)
    ny = to_market_tz(candles.index)
    flag = is_silver_bullet(candles.index).to_numpy()

    for hour, expected in ((3, True), (10, True), (14, True), (9, False), (16, False)):
        at_hour = flag[(ny.hour == hour) & (ny.minute == 30)]
        assert at_hour[0] == expected, f"{hour}:30 should be {expected}"


def test_window_is_half_open_at_its_end():
    candles = minutes(24)
    ny = to_market_tz(candles.index)
    london = in_window(candles.index, window_by_name("london")).to_numpy()

    assert london[(ny.hour == 2) & (ny.minute == 0)][0]
    assert not london[(ny.hour == 5) & (ny.minute == 0)][0]


def test_dst_shift_does_not_move_the_new_york_session():
    # US clocks went forward on 10 March 2024. The London kill zone must still
    # start at 02:00 New York on both sides of it, at different UTC hours.
    before = minutes(24, start="2024-03-08 00:00")
    after = minutes(24, start="2024-03-12 00:00")

    for candles in (before, after):
        london = in_window(candles.index, window_by_name("london"))
        started = candles.index[london.to_numpy()][0]
        assert to_market_tz(pd.DatetimeIndex([started]))[0].hour == 2

    before_utc = before.index[
        in_window(before.index, window_by_name("london")).to_numpy()
    ][0].hour
    after_utc = after.index[
        in_window(after.index, window_by_name("london")).to_numpy()
    ][0].hour
    assert before_utc != after_utc
