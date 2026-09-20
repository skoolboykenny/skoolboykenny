import pandas as pd
import pytest

from ict.data.loader import (
    clean,
    find_gaps,
    load_csvs,
    read_parquet,
    write_parquet,
)
from ict.detectors.levels import available_at, session_levels

from .conftest import make_candles


def write_histdata(path, lines: list[str]) -> str:
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_histdata_timestamps_are_read_as_est_and_stored_as_utc(tmp_path):
    # HistData stamps in EST all year, so 08:00 EST is 13:00 UTC, in March too.
    path = write_histdata(
        tmp_path / "eurusd.csv",
        [
            "20240304 080000;1.08500;1.08550;1.08480;1.08520;0",
            "20240304 080100;1.08520;1.08560;1.08500;1.08540;0",
        ],
    )
    candles, report = load_csvs([path], source="histdata")

    assert report.rows_kept == 2
    assert str(candles.index.tz) == "UTC"
    assert candles.index[0] == pd.Timestamp("2024-03-04 13:00", tz="UTC")


def test_duplicate_timestamps_are_dropped(tmp_path):
    path = write_histdata(
        tmp_path / "dupes.csv",
        [
            "20240304 080000;1.0850;1.0855;1.0848;1.0852;0",
            "20240304 080000;1.0850;1.0855;1.0848;1.0853;0",
            "20240304 080100;1.0852;1.0856;1.0850;1.0854;0",
        ],
    )
    candles, report = load_csvs([path], source="histdata")

    assert report.duplicates_dropped == 1
    assert len(candles) == 2
    # The last occurrence wins.
    assert candles.iloc[0]["close"] == pytest.approx(1.0853)


def test_inconsistent_ohlc_rows_are_dropped():
    frame = make_candles(
        [
            (10, 11, 9, 10),
            (10, 9, 11, 10),  # high below low: impossible
            (10, 11, 9, 10),
        ]
    )
    cleaned, report = clean(frame)

    assert report.inconsistent_dropped == 1
    assert len(cleaned) == 2


def test_non_positive_prices_are_dropped():
    frame = make_candles([(10, 11, 9, 10), (0, 0, 0, 0)])
    cleaned, report = clean(frame)

    assert report.non_positive_dropped == 1
    assert len(cleaned) == 1


def test_flat_zero_volume_weekend_bars_are_dropped():
    # 2024-03-09 is a Saturday.
    frame = make_candles(
        [(10, 10, 10, 10)] * 3, start="2024-03-09 08:00", volume=0.0
    )
    cleaned, report = clean(frame)

    assert report.zero_volume_weekend_dropped == 3
    assert cleaned.empty


def test_weekday_flat_bars_are_kept():
    frame = make_candles([(10, 10, 10, 10)] * 3, start="2024-03-04 08:00", volume=0.0)
    cleaned, report = clean(frame)

    assert report.zero_volume_weekend_dropped == 0
    assert len(cleaned) == 3


def test_gaps_are_reported_but_never_filled():
    first = make_candles([(10, 11, 9, 10)] * 3, start="2024-03-04 08:00")
    second = make_candles([(10, 11, 9, 10)] * 3, start="2024-03-04 12:00")
    candles, _ = clean(pd.concat([first, second]))

    assert len(candles) == 6  # nothing invented across the four hour hole

    gaps = find_gaps(candles, minimum="10min")
    assert len(gaps) == 1
    assert gaps.iloc[0]["duration"] == pd.Timedelta(hours=3, minutes=58)


def test_parquet_round_trip_preserves_the_utc_index(tmp_path):
    candles = make_candles([(10, 11, 9, 10)] * 5)
    path = write_parquet(candles, tmp_path / "out" / "candles.parquet")
    restored = read_parquet(path)

    assert str(restored.index.tz) == "UTC"
    # freq is an index attribute, not data, and Parquet does not carry it.
    pd.testing.assert_frame_equal(candles, restored, check_freq=False)


def test_dukascopy_csv_is_read(tmp_path):
    path = tmp_path / "duka.csv"
    path.write_text(
        "time,open,high,low,close,volume\n"
        "2024-03-04 13:00:00,1.0850,1.0855,1.0848,1.0852,120\n"
        "2024-03-04 13:01:00,1.0852,1.0856,1.0850,1.0854,140\n"
    )
    candles, report = load_csvs([str(path)], source="dukascopy")

    assert report.rows_kept == 2
    assert candles.index[0] == pd.Timestamp("2024-03-04 13:00", tz="UTC")


def test_unknown_source_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown source"):
        load_csvs([str(tmp_path / "x.csv")], source="nonsense")


def test_session_levels_are_not_available_before_they_are_finished():
    # A full New York day of 1 minute candles.
    index = pd.date_range(
        pd.Timestamp("2024-03-04 00:00", tz="America/New_York").tz_convert("UTC"),
        periods=24 * 60,
        freq="1min",
    )
    candles = pd.DataFrame(
        {"open": 1.0, "high": 1.5, "low": 0.5, "close": 1.2, "volume": 10.0},
        index=index.rename("timestamp"),
    )
    levels = session_levels(candles)

    assert "midnight_open" in set(levels["name"])

    # At 00:30 New York the Asian range for the day has not closed yet.
    at_0030 = available_at(
        levels, pd.Timestamp("2024-03-04 00:30", tz="America/New_York")
    )
    assert "asian_high" not in set(at_0030["name"])
    assert "midnight_open" in set(at_0030["name"])
