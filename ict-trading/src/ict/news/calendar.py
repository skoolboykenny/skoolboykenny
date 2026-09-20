"""The economic calendar: loading it, and the surprise it produces.

The record names Forex Factory as the source. It has no official API and its
terms restrict scraping, so this module reads files rather than fetching them:
the weekly calendar export for live use, and a licensed or open historical
calendar for backtests. Nothing here goes to the network, deliberately.

Two things come out of a calendar. A **gate**, which is code and cannot be
overridden: no ICT entry near a high impact release. And a **surprise**, actual
minus forecast scaled by that event's own history, which is the feature the
news playbooks trade and the only part the backtest can learn from.

Scaling matters more than it looks. A CPI miss of 0.1 and an NFP miss of 0.1
are not the same event: payrolls are quoted in thousands and inflation in
percent, so an unscaled surprise ranks every payroll release above every
inflation release regardless of what the market did. Surprises are therefore
divided by the event's own historical spread and compared in those units.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import MARKET_TZ, STORAGE_TZ

#: Impact levels, weakest first. Only ``high`` gates the ICT models.
IMPACT_LEVELS = ("low", "medium", "high")

#: Events the record singles out as behaving differently from the rest. Tracked
#: separately because lumping NFP in with retail sales averages away the thing
#: that makes either worth knowing about.
TIER_ONE = ("nfp", "non-farm", "nonfarm", "cpi", "fomc", "interest rate", "gdp")

#: Minutes either side of a high impact release with no new ICT entries.
DEFAULT_BLACKOUT_MINUTES = 15

#: FOMC is flagged separately: the record treats the whole day as different,
#: not just the fifteen minutes around the statement.
FOMC_KEYWORDS = ("fomc", "federal funds", "interest rate decision")

_COLUMN_ALIASES = {
    "date": "date",
    "time": "time",
    "datetime": "timestamp",
    "timestamp": "timestamp",
    "currency": "currency",
    "country": "currency",
    "impact": "impact",
    "importance": "impact",
    "event": "event",
    "title": "event",
    "name": "event",
    "actual": "actual",
    "forecast": "forecast",
    "consensus": "forecast",
    "previous": "previous",
    "revised": "revised",
    "revised_from": "revised",
}


@dataclass(frozen=True)
class Event:
    """One calendar release."""

    time: pd.Timestamp
    currency: str
    impact: str
    name: str
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    revised: float | None = None

    @property
    def is_high_impact(self) -> bool:
        return self.impact == "high"

    @property
    def is_fomc(self) -> bool:
        lowered = self.name.lower()
        return any(word in lowered for word in FOMC_KEYWORDS)

    @property
    def is_tier_one(self) -> bool:
        lowered = self.name.lower()
        return any(word in lowered for word in TIER_ONE)

    @property
    def surprise(self) -> float | None:
        """Actual minus forecast, in the event's own units.

        ``None`` before the release, which is the point: a backtest that reads
        a surprise before its release time is reading the future.
        """
        if self.actual is None or self.forecast is None:
            return None
        return self.actual - self.forecast

    @property
    def revision(self) -> float | None:
        """How much the previous figure was revised by, and in which direction.

        The record flags this: a strong actual alongside a large downward
        revision to previous often reverses, because the level is unchanged and
        only the path to it moved.
        """
        if self.revised is None or self.previous is None:
            return None
        return self.previous - self.revised

    @property
    def expected_direction(self) -> int:
        """The sign of forecast minus previous, which is playbook A's prior."""
        if self.forecast is None or self.previous is None:
            return 0
        difference = self.forecast - self.previous
        return int(np.sign(difference))


def _parse_number(value) -> float | None:
    """Read a calendar figure, which arrives decorated.

    Calendars quote ``250K``, ``3.2%``, ``-1.5B`` and blanks. Suffixes are
    scaled rather than stripped, because 250K against a forecast of 0.25M is
    the same number and must compare as one.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None if pd.isna(value) else float(value)

    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"-", "--", "n/a", "N/A"}:
        return None

    multiplier = 1.0
    if text[-1] in "KkMmBbTt":
        multiplier = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}[text[-1].lower()]
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _parse_impact(value) -> str:
    """Normalise the many ways a calendar says "this one matters"."""
    text = str(value).strip().lower()
    if text in IMPACT_LEVELS:
        return text
    if text in {"3", "red", "high impact expected"}:
        return "high"
    if text in {"2", "orange", "medium impact expected"}:
        return "medium"
    if text in {"1", "yellow", "low impact expected"}:
        return "low"
    if "high" in text or "red" in text:
        return "high"
    if "med" in text or "orange" in text:
        return "medium"
    return "low"


def read_calendar(
    path: str | Path, timezone: str = MARKET_TZ, currencies: tuple[str, ...] | None = None
) -> pd.DataFrame:
    """Read a calendar export into a UTC indexed frame.

    ``timezone`` is the zone the file's times are in. Forex Factory exports in
    whatever the account is set to, and getting this wrong shifts every gate by
    hours without any error, so it is explicit rather than guessed.

    Columns are matched by alias, because no two calendar exports agree on
    names. Anything unrecognised is ignored rather than guessed at.
    """
    path = Path(path)
    raw = pd.read_csv(path)
    raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]

    frame = pd.DataFrame()
    for source, target in _COLUMN_ALIASES.items():
        if source in raw.columns and target not in frame.columns:
            frame[target] = raw[source]

    if "timestamp" in frame.columns:
        stamps = pd.to_datetime(frame["timestamp"], errors="coerce")
    elif "date" in frame.columns:
        times = frame["time"] if "time" in frame.columns else "00:00"
        stamps = pd.to_datetime(
            frame["date"].astype(str) + " " + pd.Series(times, index=frame.index).astype(str),
            errors="coerce",
        )
    else:
        raise ValueError(
            f"{path.name} has no date or timestamp column. Found: {list(raw.columns)}"
        )

    if getattr(stamps.dtype, "tz", None) is None:
        stamps = stamps.dt.tz_localize(
            timezone, ambiguous="NaT", nonexistent="shift_forward"
        )
    frame["time"] = stamps.dt.tz_convert(STORAGE_TZ)

    frame = frame.loc[frame["time"].notna()].copy()
    frame["currency"] = (
        frame["currency"].astype(str).str.strip().str.upper()
        if "currency" in frame.columns
        else "USD"
    )
    frame["impact"] = (
        frame["impact"].map(_parse_impact) if "impact" in frame.columns else "low"
    )
    frame["event"] = (
        frame["event"].astype(str).str.strip() if "event" in frame.columns else ""
    )
    for field in ("actual", "forecast", "previous", "revised"):
        frame[field] = (
            frame[field].map(_parse_number) if field in frame.columns else None
        )

    if currencies:
        wanted = {c.upper() for c in currencies}
        frame = frame.loc[frame["currency"].isin(wanted)]

    frame = frame.sort_values("time").reset_index(drop=True)
    return frame[
        ["time", "currency", "impact", "event", "actual", "forecast", "previous", "revised"]
    ]


def events(frame: pd.DataFrame) -> list[Event]:
    """The frame as :class:`Event` objects, for the playbooks."""
    return [
        Event(
            time=row.time,
            currency=row.currency,
            impact=row.impact,
            name=row.event,
            actual=row.actual,
            forecast=row.forecast,
            previous=row.previous,
            revised=row.revised,
        )
        for row in frame.itertuples()
    ]


def scaled_surprise(frame: pd.DataFrame, minimum_history: int = 8) -> pd.Series:
    """Each surprise divided by that event's own historical spread.

    Comparable across events, which a raw surprise is not: payrolls are quoted
    in thousands and inflation in percent. An event with too little history
    gets ``NaN`` rather than a number computed from three observations, because
    a scale estimated from three points is noise wearing a unit.

    The scale for a row uses only rows before it. Using the whole history would
    let a 2021 release be scaled by a spread that includes 2024, which is
    lookahead in a place nobody checks for it.
    """
    surprise = frame["actual"] - frame["forecast"]
    out = pd.Series(np.nan, index=frame.index, dtype="float64")

    for name, group in frame.groupby(frame["event"].str.lower(), sort=False):
        values = surprise.loc[group.index]
        # Expanding, shifted: the scale for a row is built from earlier rows only.
        scale = values.abs().expanding().mean().shift(1)
        enough = values.expanding().count().shift(1) >= minimum_history
        out.loc[group.index] = np.where(
            enough & (scale > 0), values / scale, np.nan
        )
    return out
