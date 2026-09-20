"""Tests for the data collection scripts.

The scripts live outside the package, so they are loaded by path. What matters
here is the logic that would otherwise only be exercised by a download: chunk
bookkeeping, the CSV format dukascopy-node actually writes, and the gap
classification that decides whether a hole is the weekend or a missing file.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    # `@dataclass` looks the defining module up in sys.modules while the class
    # body executes, so it has to be registered before the module runs.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


download_data = _load("download_data")
build_parquet = _load("build_parquet")


def write_chunk(
    directory: Path,
    instrument: str,
    price_type: str,
    start: str,
    end: str,
    index: pd.DatetimeIndex,
    price: float,
) -> Path:
    """Write a chunk in exactly the format dukascopy-node produces."""
    directory.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            # Explicit milliseconds: pandas 3 stores datetimes as microseconds,
            # so a bare astype("int64") is not nanoseconds.
            "timestamp": index.tz_convert("UTC").tz_localize(None)
            .astype("datetime64[ms]")
            .astype("int64"),
            "open": price,
            "high": price + 0.0005,
            "low": price - 0.0005,
            "close": price,
            "volume": 100.0,
        }
    )
    path = directory / f"{instrument}-m1-{price_type}-{start}-{end}.csv"
    frame.to_csv(path, index=False)
    return path


# --- download_data ----------------------------------------------------------


def test_month_starts_covers_every_month_in_range():
    months = download_data.month_starts(date(2021, 1, 1), date(2021, 4, 1))
    assert months == [date(2021, 1, 1), date(2021, 2, 1), date(2021, 3, 1)]


def test_month_starts_crosses_the_year_boundary():
    months = download_data.month_starts(date(2021, 11, 1), date(2022, 2, 1))
    assert months == [date(2021, 11, 1), date(2021, 12, 1), date(2022, 1, 1)]


def test_chunks_cover_every_instrument_and_price_type():
    chunks = download_data.build_chunks(
        ("eurusd", "gbpusd"), ("bid", "ask"), date(2021, 1, 1), date(2021, 3, 1)
    )
    # 2 instruments x 2 price types x 2 months
    assert len(chunks) == 8
    assert {(c.instrument, c.price_type) for c in chunks} == {
        ("eurusd", "bid"),
        ("eurusd", "ask"),
        ("gbpusd", "bid"),
        ("gbpusd", "ask"),
    }


def test_last_chunk_ends_at_the_requested_end_date():
    chunks = download_data.build_chunks(
        ("eurusd",), ("bid",), date(2021, 1, 1), date(2021, 3, 15)
    )
    assert chunks[-1].start == date(2021, 3, 1)
    assert chunks[-1].end == date(2021, 3, 15)


def test_months_limit_applies_per_instrument_and_price_type():
    chunks = download_data.build_chunks(
        ("eurusd", "gbpusd"),
        ("bid", "ask"),
        date(2021, 1, 1),
        date(2021, 6, 1),
        limit=1,
    )
    # One month each, so a trial run still covers every combination.
    assert len(chunks) == 4
    assert {c.start for c in chunks} == {date(2021, 1, 1)}


def test_command_matches_the_documented_cli_invocation():
    chunk = download_data.Chunk("eurusd", "bid", date(2021, 1, 1), date(2021, 2, 1))
    command = chunk.command()

    assert command[:3] == ["npx", "--yes", "dukascopy-node"]
    for flag, value in (
        ("-i", "eurusd"),
        ("-from", "2021-01-01"),
        ("-to", "2021-02-01"),
        ("-t", "m1"),
        ("-p", "bid"),
        ("-f", "csv"),
    ):
        assert command[command.index(flag) + 1] == value
    assert "-v" in command


def test_an_empty_file_does_not_count_as_downloaded(tmp_path, monkeypatch):
    # The CLI exits 0 and writes zero bytes when the feed is unreachable.
    monkeypatch.setattr(download_data, "RAW", tmp_path)
    chunk = download_data.Chunk("eurusd", "bid", date(2021, 1, 1), date(2021, 2, 1))

    chunk.path.parent.mkdir(parents=True)
    chunk.path.touch()
    assert chunk.is_downloaded() is False

    chunk.path.write_text("timestamp,open,high,low,close,volume\n1,1,1,1,1,1\n")
    assert chunk.is_downloaded() is True


# --- build_parquet ----------------------------------------------------------


def test_read_chunk_parses_epoch_millisecond_timestamps(tmp_path):
    index = pd.date_range("2021-01-04 00:00", periods=3, freq="1min", tz="UTC")
    path = write_chunk(
        tmp_path, "eurusd", "bid", "2021-01-01", "2021-02-01", index, 1.2300
    )
    frame = build_parquet.read_chunk(path)

    assert str(frame.index.tz) == "UTC"
    assert frame.index[0] == pd.Timestamp("2021-01-04 00:00", tz="UTC")
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]


def test_read_chunk_rejects_a_file_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("timestamp,open\n1609718400000,1.23\n")
    with pytest.raises(ValueError, match="missing columns"):
        build_parquet.read_chunk(path)


def test_merge_derives_mid_prices_and_spread():
    index = pd.date_range("2021-01-04 00:00", periods=2, freq="1min", tz="UTC")
    bid = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 10.0},
        index=index,
    )
    ask = pd.DataFrame(
        {"open": 1.2, "high": 1.2, "low": 1.2, "close": 1.2, "volume": 4.0},
        index=index,
    )
    merged = build_parquet.merge_sides(bid, ask)

    assert merged["mid_close"].iloc[0] == pytest.approx(1.1)
    assert merged["spread"].iloc[0] == pytest.approx(0.2)
    assert merged["volume"].iloc[0] == pytest.approx(14.0)


def test_merge_keeps_only_minutes_quoted_on_both_sides():
    bid_index = pd.date_range("2021-01-04 00:00", periods=5, freq="1min", tz="UTC")
    ask_index = bid_index[:3]
    bid = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
        index=bid_index,
    )
    ask = pd.DataFrame(
        {"open": 1.1, "high": 1.1, "low": 1.1, "close": 1.1, "volume": 1.0},
        index=ask_index,
    )
    merged = build_parquet.merge_sides(bid, ask)

    assert len(merged) == 3
    assert not merged.isna().any().any()


def test_the_weekend_close_is_not_reported_as_a_gap():
    # Friday 2021-01-08 20:59 UTC to Sunday 2021-01-10 22:00 UTC.
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2021-01-08 20:58", tz="UTC"),
            pd.Timestamp("2021-01-08 20:59", tz="UTC"),
            pd.Timestamp("2021-01-10 22:00", tz="UTC"),
            pd.Timestamp("2021-01-10 22:01", tz="UTC"),
        ]
    )
    frame = pd.DataFrame({"spread": 0.0}, index=index)

    assert build_parquet.find_gaps(frame).empty


def test_a_weekday_hole_is_reported():
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2021-01-06 10:00", tz="UTC"),
            pd.Timestamp("2021-01-06 10:01", tz="UTC"),
            pd.Timestamp("2021-01-06 14:00", tz="UTC"),
        ]
    )
    frame = pd.DataFrame({"spread": 0.0}, index=index)
    gaps = build_parquet.find_gaps(frame)

    assert len(gaps) == 1
    assert gaps.iloc[0]["duration"] == timedelta(hours=3, minutes=59)


def test_gaps_under_the_threshold_are_ignored():
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2021-01-06 10:00", tz="UTC"),
            pd.Timestamp("2021-01-06 10:04", tz="UTC"),
        ]
    )
    frame = pd.DataFrame({"spread": 0.0}, index=index)
    assert build_parquet.find_gaps(frame).empty


def test_a_multi_week_hole_is_reported_even_though_it_spans_weekends():
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2021-01-06 10:00", tz="UTC"),
            pd.Timestamp("2021-01-27 10:00", tz="UTC"),
        ]
    )
    frame = pd.DataFrame({"spread": 0.0}, index=index)
    gaps = build_parquet.find_gaps(frame)

    assert len(gaps) == 1


def test_build_end_to_end_writes_parquet_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(build_parquet, "RAW", tmp_path / "raw")
    monkeypatch.setattr(build_parquet, "PROCESSED", tmp_path / "processed")

    # A weekday run, then a genuine weekend break, then more trading.
    week_one = pd.date_range("2021-01-06 10:00", periods=120, freq="1min", tz="UTC")
    week_two = pd.date_range("2021-01-11 10:00", periods=120, freq="1min", tz="UTC")
    index = week_one.append(week_two)

    for price_type, price in (("bid", 1.2300), ("ask", 1.2302)):
        write_chunk(
            tmp_path / "raw" / "eurusd" / price_type,
            "eurusd",
            price_type,
            "2021-01-01",
            "2021-02-01",
            index,
            price,
        )

    summary = build_parquet.build("eurusd")

    assert summary["rows"] == 240
    assert summary["median_spread"] == pytest.approx(0.0002)
    assert (tmp_path / "processed" / "eurusd_m1.parquet").exists()

    restored = pd.read_parquet(tmp_path / "processed" / "eurusd_m1.parquet")
    assert list(restored.columns)[:4] == ["bid_open", "bid_high", "bid_low", "bid_close"]
    assert "mid_close" in restored.columns


def test_empty_chunks_are_skipped_not_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(build_parquet, "RAW", tmp_path / "raw")
    directory = tmp_path / "raw" / "eurusd" / "bid"
    directory.mkdir(parents=True)
    (directory / "eurusd-m1-bid-2021-01-01-2021-02-01.csv").touch()

    with pytest.raises(FileNotFoundError, match="empty or missing"):
        build_parquet.load_side("eurusd", "bid")
