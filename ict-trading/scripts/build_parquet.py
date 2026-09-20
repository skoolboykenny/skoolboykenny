#!/usr/bin/env python3
"""Merge downloaded monthly chunks into one Parquet file per instrument.

Bid and ask are downloaded separately and joined here on the minute, giving
both sides, the mid prices the detectors work on, and the spread that decides
whether a minute was tradeable at all.

    python scripts/build_parquet.py
    python scripts/build_parquet.py --instruments eurusd

Output columns:

    timestamp_utc                          UTC, minute resolution
    bid_open bid_high bid_low bid_close    bid side
    ask_open ask_high ask_low ask_close    ask side
    mid_open mid_high mid_low mid_close    (bid + ask) / 2
    spread                                 ask_close - bid_close
    volume                                 bid volume + ask volume

Gaps longer than five minutes are reported, excluding the weekend close, so
what is left is either a market holiday or a hole in the download.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
DATA_MD = ROOT / "DATA.md"

INSTRUMENTS = ("eurusd", "gbpusd")
PRICE_TYPES = ("bid", "ask")
OHLC = ("open", "high", "low", "close")

GAP_THRESHOLD = timedelta(minutes=5)

SUMMARY_START = "<!-- SUMMARY:START -->"
SUMMARY_END = "<!-- SUMMARY:END -->"


def read_chunk(path: Path) -> pd.DataFrame:
    """Read one dukascopy-node CSV chunk into a UTC indexed frame.

    The CLI writes `timestamp,open,high,low,close,volume` with the timestamp
    in epoch milliseconds unless `--date-format` was passed, so both that and
    an ISO string are accepted.
    """
    frame = pd.read_csv(path)
    expected = {"timestamp", *OHLC}
    missing = expected - set(frame.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")

    stamps = frame["timestamp"]
    if pd.api.types.is_numeric_dtype(stamps):
        index = pd.to_datetime(stamps, unit="ms", utc=True)
    else:
        index = pd.to_datetime(stamps, utc=True, format="ISO8601")

    frame = frame.drop(columns=["timestamp"])
    frame.index = pd.DatetimeIndex(index, name="timestamp_utc")
    if "volume" not in frame.columns:
        frame["volume"] = 0.0
    return frame.astype("float64")


def load_side(instrument: str, price_type: str) -> tuple[pd.DataFrame, int, int]:
    """Read every chunk for one side. Returns (frame, files_read, duplicates)."""
    directory = RAW / instrument / price_type
    if not directory.exists():
        raise FileNotFoundError(
            f"no chunks at {directory}. Run scripts/download_data.py first."
        )

    paths = sorted(p for p in directory.glob("*.csv") if p.stat().st_size > 0)
    empty = [p for p in directory.glob("*.csv") if p.stat().st_size == 0]
    for path in empty:
        print(f"  warning: {path.name} is empty, skipped", file=sys.stderr)

    if not paths:
        raise FileNotFoundError(f"every chunk in {directory} is empty or missing")

    frames = [read_chunk(path) for path in paths]
    combined = pd.concat(frames).sort_index()

    duplicated = combined.index.duplicated(keep="last")
    combined = combined.loc[~duplicated]
    return combined, len(paths), int(duplicated.sum())


def merge_sides(bid: pd.DataFrame, ask: pd.DataFrame) -> pd.DataFrame:
    """Join bid and ask on the minute and derive mid prices and spread.

    An inner join is deliberate: a minute with only one side quoted cannot
    produce a mid price or a spread, and carrying it with half its columns
    empty would push that decision into every consumer downstream.
    """
    bid = bid.add_prefix("bid_")
    ask = ask.add_prefix("ask_")
    merged = bid.join(ask, how="inner")

    for field in OHLC:
        merged[f"mid_{field}"] = (
            merged[f"bid_{field}"] + merged[f"ask_{field}"]
        ) / 2.0

    merged["spread"] = merged["ask_close"] - merged["bid_close"]
    merged["volume"] = merged["bid_volume"] + merged["ask_volume"]
    merged = merged.drop(columns=["bid_volume", "ask_volume"])

    columns = (
        [f"bid_{f}" for f in OHLC]
        + [f"ask_{f}" for f in OHLC]
        + [f"mid_{f}" for f in OHLC]
        + ["spread", "volume"]
    )
    return merged[columns]


def _in_weekend_window(stamp: pd.Timestamp) -> bool:
    """Is this timestamp inside the forex weekend close?

    The week closes at 17:00 New York on Friday and reopens at 17:00 New York
    on Sunday, which is 22:00 UTC in northern winter and 21:00 UTC in summer.
    The window below is widened to the outside of both, so a real hole inside
    that two hour band would be missed rather than a normal weekend being
    reported every week. This only ever classifies a gap; nothing is filled.
    """
    weekday = stamp.weekday()
    if weekday == 5:  # Saturday
        return True
    if weekday == 4 and stamp.hour >= 20:  # Friday evening, either offset
        return True
    if weekday == 6 and stamp.hour < 22:  # Sunday before the reopen
        return True
    return False


def find_gaps(frame: pd.DataFrame) -> pd.DataFrame:
    """Gaps longer than five minutes that are not the weekend close."""
    if len(frame) < 2:
        return pd.DataFrame(columns=["start", "end", "duration"])

    starts = frame.index[:-1]
    ends = frame.index[1:]
    durations = ends - starts

    gaps = pd.DataFrame(
        {"start": starts, "end": ends, "duration": durations}
    )
    gaps = gaps.loc[gaps["duration"] > GAP_THRESHOLD].reset_index(drop=True)
    if gaps.empty:
        return gaps

    weekend = gaps.apply(
        lambda row: (
            row["duration"] <= timedelta(days=3)
            and _in_weekend_window(row["start"])
            and _in_weekend_window(row["end"] - timedelta(minutes=1))
        ),
        axis=1,
    )
    gaps = gaps.loc[~weekend.to_numpy()]
    return gaps.sort_values("duration", ascending=False).reset_index(drop=True)


def build(instrument: str) -> dict:
    """Build one instrument's Parquet file and return its summary."""
    print(f"{instrument}:")

    sides = {}
    files_read = 0
    duplicates = 0
    for price_type in PRICE_TYPES:
        frame, count, dupes = load_side(instrument, price_type)
        sides[price_type] = frame
        files_read += count
        duplicates += dupes
        print(f"  {price_type}: {len(frame):,} rows from {count} chunks")

    merged = merge_sides(sides["bid"], sides["ask"])
    gaps = find_gaps(merged)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    out = PROCESSED / f"{instrument}_m1.parquet"
    merged.to_parquet(out, engine="pyarrow", index=True)

    print(f"  merged: {len(merged):,} rows, {duplicates:,} duplicate timestamps dropped")
    print(f"  gaps over 5 minutes outside weekends: {len(gaps)}")
    if not gaps.empty:
        print(gaps.head(10).to_string(index=False))
    print(f"  wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")

    try:
        listed = str(out.relative_to(ROOT))
    except ValueError:
        listed = str(out)

    return {
        "instrument": instrument,
        "rows": int(len(merged)),
        "first": str(merged.index[0]) if len(merged) else None,
        "last": str(merged.index[-1]) if len(merged) else None,
        "gaps": int(len(gaps)),
        "chunks": files_read,
        "duplicates_dropped": duplicates,
        "median_spread": float(merged["spread"].median()) if len(merged) else None,
        "file": listed,
    }


def summary_table(summaries: list[dict]) -> str:
    """The Markdown table DATA.md carries."""
    lines = [
        "| Instrument | Rows | First | Last | Gaps over 5 min | Median spread |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in summaries:
        spread = (
            f"{item['median_spread']:.5f}" if item["median_spread"] is not None else "n/a"
        )
        lines.append(
            f"| {item['instrument'].upper()} | {item['rows']:,} | "
            f"{item['first']} | {item['last']} | {item['gaps']} | {spread} |"
        )
    return "\n".join(lines)


def update_data_md(summaries: list[dict]) -> bool:
    """Rewrite the summary table in DATA.md between its markers."""
    if not DATA_MD.exists():
        return False
    text = DATA_MD.read_text()
    if SUMMARY_START not in text or SUMMARY_END not in text:
        return False

    before = text.split(SUMMARY_START)[0]
    after = text.split(SUMMARY_END)[1]
    generated = pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    block = (
        f"{SUMMARY_START}\n\n"
        f"{summary_table(summaries)}\n\n"
        f"Generated by `scripts/build_parquet.py` on {generated}.\n\n"
        f"{SUMMARY_END}"
    )
    DATA_MD.write_text(before + block + after)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instruments", nargs="*", default=list(INSTRUMENTS), choices=list(INSTRUMENTS)
    )
    parser.add_argument(
        "--no-docs", action="store_true", help="do not update the table in DATA.md"
    )
    args = parser.parse_args(argv)

    summaries = []
    for instrument in args.instruments:
        try:
            summaries.append(build(instrument))
        except FileNotFoundError as error:
            print(f"{instrument}: {error}", file=sys.stderr)

    if not summaries:
        print("nothing built", file=sys.stderr)
        return 1

    PROCESSED.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "summary.json").write_text(json.dumps(summaries, indent=2))

    if not args.no_docs and update_data_md(summaries):
        print(f"updated the summary table in {DATA_MD.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
