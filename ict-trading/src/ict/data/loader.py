"""Load 1 minute OHLC from vendor CSV and store it as Parquet.

Two free sources are supported, because they are the two the plan names:

``histdata``
    HistData's "ASCII M1 bars" export. Semicolon separated, no header:
    ``YYYYMMDD HHMMSS;open;high;low;close;volume``. Timestamps are Eastern
    Standard Time with no daylight saving shift, which is not a timezone any
    library models, so they are read as fixed UTC-5.

``dukascopy``
    Comma separated with a header, timestamps in UTC:
    ``time,open,high,low,close,volume``.

Whatever goes in, what comes out is always the same: a UTC indexed frame with
the columns in :data:`~ict.config.OHLC_COLUMNS`, sorted, de-duplicated, and
free of the zero-volume filler rows vendors emit across the weekend.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..config import OHLC_COLUMNS, STORAGE_TZ

#: HistData stamps its bars in EST all year, with no daylight saving.
HISTDATA_TZ = "Etc/GMT+5"


@dataclass(frozen=True)
class LoadReport:
    """What cleaning had to do, so data problems are visible, not silent."""

    rows_read: int
    duplicates_dropped: int
    non_positive_dropped: int
    inconsistent_dropped: int
    zero_volume_weekend_dropped: int
    rows_kept: int
    first: pd.Timestamp | None
    last: pd.Timestamp | None

    def summary(self) -> str:
        lines = [
            f"read {self.rows_read:,} rows, kept {self.rows_kept:,}",
            f"  duplicate timestamps   {self.duplicates_dropped:,}",
            f"  non-positive prices    {self.non_positive_dropped:,}",
            f"  inconsistent OHLC      {self.inconsistent_dropped:,}",
            f"  weekend filler bars    {self.zero_volume_weekend_dropped:,}",
        ]
        if self.first is not None:
            lines.append(f"  span {self.first} to {self.last}")
        return "\n".join(lines)


def read_histdata_csv(path: str | Path) -> pd.DataFrame:
    """Read one HistData ASCII M1 file into a raw, UTC indexed frame."""
    raw = pd.read_csv(
        path,
        sep=";",
        header=None,
        names=["timestamp", *OHLC_COLUMNS],
        dtype={"timestamp": str},
    )
    stamps = pd.to_datetime(raw["timestamp"], format="%Y%m%d %H%M%S")
    index = stamps.dt.tz_localize(HISTDATA_TZ).dt.tz_convert(STORAGE_TZ)
    frame = raw[list(OHLC_COLUMNS)].copy()
    frame.index = pd.DatetimeIndex(index, name="timestamp")
    return frame


def _parse_timestamps(column: pd.Series) -> pd.Series:
    """Parse a timestamp column, trying ISO order before day-first order.

    Order matters. Dukascopy's own export is day first (``04.03.2024``) but
    plenty of exports are ISO (``2024-03-04``), and parsing an ISO date with
    ``dayfirst=True`` silently turns 4 March into 3 April rather than failing.
    So ISO is tried first and day first is only the fallback.
    """
    try:
        return pd.to_datetime(column, format="ISO8601")
    except (ValueError, TypeError):
        return pd.to_datetime(column, format="mixed", dayfirst=True)


def read_dukascopy_csv(path: str | Path) -> pd.DataFrame:
    """Read one Dukascopy style CSV into a raw, UTC indexed frame."""
    raw = pd.read_csv(path)
    raw.columns = [c.strip().lower() for c in raw.columns]
    time_column = next(
        (c for c in ("time", "timestamp", "gmt time", "date") if c in raw.columns),
        None,
    )
    if time_column is None:
        raise ValueError(f"no recognisable time column in {path}")

    stamps = _parse_timestamps(raw[time_column])
    if stamps.dt.tz is None:
        stamps = stamps.dt.tz_localize(STORAGE_TZ)
    else:
        stamps = stamps.dt.tz_convert(STORAGE_TZ)

    missing = [c for c in OHLC_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"missing columns {missing} in {path}")

    frame = raw[list(OHLC_COLUMNS)].copy()
    frame.index = pd.DatetimeIndex(stamps, name="timestamp")
    return frame


_READERS = {"histdata": read_histdata_csv, "dukascopy": read_dukascopy_csv}


def clean(frame: pd.DataFrame) -> tuple[pd.DataFrame, LoadReport]:
    """Sort, de-duplicate and sanity check a raw candle frame.

    Gaps are left as gaps. A missing minute is genuine information (the market
    was shut, or the feed dropped) and filling it would manufacture candles
    detectors would then find structure in.
    """
    rows_read = len(frame)
    frame = frame.sort_index()

    duplicated = frame.index.duplicated(keep="last")
    duplicates_dropped = int(duplicated.sum())
    frame = frame.loc[~duplicated]

    prices = frame[["open", "high", "low", "close"]]
    positive = (prices > 0).all(axis=1)
    non_positive_dropped = int((~positive).sum())
    frame = frame.loc[positive]

    prices = frame[["open", "high", "low", "close"]]
    consistent = (frame["high"] >= prices.max(axis=1)) & (
        frame["low"] <= prices.min(axis=1)
    )
    inconsistent_dropped = int((~consistent).sum())
    frame = frame.loc[consistent]

    # Vendors pad the weekend with flat, zero volume bars. They are not trades.
    weekend = frame.index.dayofweek >= 5
    flat = (frame["high"] == frame["low"]) & (frame["volume"] <= 0)
    filler = weekend & flat
    zero_volume_weekend_dropped = int(filler.sum())
    frame = frame.loc[~filler]

    frame = frame[list(OHLC_COLUMNS)].astype("float64")

    report = LoadReport(
        rows_read=rows_read,
        duplicates_dropped=duplicates_dropped,
        non_positive_dropped=non_positive_dropped,
        inconsistent_dropped=inconsistent_dropped,
        zero_volume_weekend_dropped=zero_volume_weekend_dropped,
        rows_kept=len(frame),
        first=frame.index[0] if len(frame) else None,
        last=frame.index[-1] if len(frame) else None,
    )
    return frame, report


def load_csvs(
    paths: list[str | Path], source: str = "histdata"
) -> tuple[pd.DataFrame, LoadReport]:
    """Read and clean one or more vendor CSVs into a single candle frame."""
    if source not in _READERS:
        raise ValueError(f"unknown source {source!r}, expected one of {list(_READERS)}")
    reader = _READERS[source]
    frames = [reader(p) for p in paths]
    if not frames:
        raise ValueError("no input files given")
    return clean(pd.concat(frames))


def write_parquet(candles: pd.DataFrame, path: str | Path) -> Path:
    """Store a candle frame as Parquet, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    candles.to_parquet(path, engine="pyarrow", index=True)
    return path


#: Sides available in a file built by `scripts/build_parquet.py`.
PRICE_SIDES = ("mid", "bid", "ask")


def read_parquet(path: str | Path, side: str = "mid") -> pd.DataFrame:
    """Read a stored candle frame back, with its UTC index intact.

    Two layouts are accepted. A plain ``open/high/low/close/volume`` frame is
    returned as it stands. A frame built by ``scripts/build_parquet.py``, which
    carries ``bid_``, ``ask_`` and ``mid_`` prices side by side, has ``side``
    lifted into the plain columns the detectors expect, with ``spread`` carried
    along so a later phase can gate on it.

    Detectors run on the mid price by default. Filling at the mid and ignoring
    the spread is what makes a backtest look better than the broker will, so
    the spread stays attached rather than being dropped here.
    """
    if side not in PRICE_SIDES:
        raise ValueError(f"side must be one of {PRICE_SIDES}, got {side!r}")

    frame = pd.read_parquet(path, engine="pyarrow")
    index = pd.DatetimeIndex(frame.index)
    if index.tz is None:
        index = index.tz_localize(STORAGE_TZ)
    else:
        index = index.tz_convert(STORAGE_TZ)
    frame.index = index.rename("timestamp")

    if set(OHLC_COLUMNS).issubset(frame.columns):
        return frame[list(OHLC_COLUMNS)]

    prefixed = [f"{side}_{field}" for field in ("open", "high", "low", "close")]
    if not set(prefixed).issubset(frame.columns):
        raise ValueError(
            f"{Path(path).name} has neither {list(OHLC_COLUMNS)} nor {prefixed}. "
            "Expected a plain candle frame or one built by build_parquet.py."
        )

    lifted = frame[prefixed].copy()
    lifted.columns = ["open", "high", "low", "close"]
    lifted["volume"] = frame["volume"] if "volume" in frame.columns else 0.0
    if "spread" in frame.columns:
        lifted["spread"] = frame["spread"]
    return lifted


def find_gaps(candles: pd.DataFrame, minimum: str = "10min") -> pd.DataFrame:
    """Report the gaps in a 1 minute series, largest first.

    Weekend closes dominate the top of this list, which is the point: anything
    large that is *not* a weekend is a data problem worth knowing about before
    a detector runs over it.
    """
    if len(candles) < 2:
        return pd.DataFrame(columns=["start", "end", "duration"])
    starts = candles.index[:-1]
    ends = candles.index[1:]
    gaps = pd.DataFrame(
        {"start": starts, "end": ends, "duration": ends - starts}
    )
    gaps = gaps.loc[gaps["duration"] > pd.Timedelta(minimum)]
    return gaps.sort_values("duration", ascending=False).reset_index(drop=True)
