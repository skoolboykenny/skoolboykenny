"""The news gate: when the ICT models are not allowed to enter.

From the record: no ICT entry from fifteen minutes before a high impact release
to fifteen minutes after it, and FOMC days flagged separately. This is a risk
check, which the record puts in the category of things code enforces and
nothing can override, so it lives here rather than inside a model where a
model could forget it.

The gate blocks **entries**, never exits. A position already open when CPI
lands still has its stop and target with the broker, and pulling them because
of a calendar entry is how a small loss becomes an unbounded one.

Two forms, for two callers. :meth:`NewsGate.blocked_at` answers for one moment,
which is what the live loop needs. :meth:`NewsGate.mask` answers for a whole
index at once, which is what the backtest needs, because asking per candle over
a million candles costs more than the detectors do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import MARKET_TZ
from .calendar import DEFAULT_BLACKOUT_MINUTES, FOMC_KEYWORDS

#: Currencies a pair is exposed to, so EUR/USD gates on both sides of itself.
PAIR_CURRENCIES = {
    "EUR_USD": ("EUR", "USD"),
    "GBP_USD": ("GBP", "USD"),
    "USD_JPY": ("USD", "JPY"),
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
}


@dataclass
class Blackout:
    """One window with no entries, and the release that caused it."""

    start: pd.Timestamp
    end: pd.Timestamp
    event: str
    currency: str
    impact: str
    #: The release itself, which is not the same as when the window opens.
    at: pd.Timestamp | None = None

    def covers(self, moment: pd.Timestamp) -> bool:
        return self.start <= moment <= self.end

    def __str__(self) -> str:
        release = (self.at or self.start).tz_convert(MARKET_TZ)
        return (
            f"{self.currency} {self.event} at {release:%a %d %b %H:%M} New York, "
            f"no entries {self.start:%H:%M} to {self.end:%H:%M} UTC"
        )


@dataclass
class NewsGate:
    """Blackout windows built from a calendar, for one instrument.

    ``calendar`` is the frame :func:`~ict.news.calendar.read_calendar` returns.
    An empty one gives a gate that blocks nothing, which is honest: no calendar
    means no knowledge of releases, not an absence of them, and the report says
    so rather than letting a run look gated when it was not.
    """

    calendar: pd.DataFrame
    instrument: str = "EUR_USD"
    minutes_before: int = DEFAULT_BLACKOUT_MINUTES
    minutes_after: int = DEFAULT_BLACKOUT_MINUTES
    block_fomc_day: bool = False
    blackouts: list[Blackout] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.blackouts = self._build()

    @property
    def currencies(self) -> tuple[str, ...]:
        return PAIR_CURRENCIES.get(self.instrument.upper(), ("USD",))

    @property
    def is_empty(self) -> bool:
        """True when there is no calendar, so nothing is being gated."""
        return self.calendar is None or self.calendar.empty

    def _build(self) -> list[Blackout]:
        if self.is_empty:
            return []

        wanted = set(self.currencies)
        relevant = self.calendar.loc[
            (self.calendar["impact"] == "high")
            & (self.calendar["currency"].isin(wanted))
        ]

        before = pd.Timedelta(minutes=self.minutes_before)
        after = pd.Timedelta(minutes=self.minutes_after)
        blackouts = [
            Blackout(
                start=row.time - before,
                end=row.time + after,
                event=row.event,
                currency=row.currency,
                impact=row.impact,
                at=row.time,
            )
            for row in relevant.itertuples()
        ]

        if self.block_fomc_day:
            blackouts.extend(self._fomc_days(relevant))
        return sorted(blackouts, key=lambda b: b.start)

    def _fomc_days(self, relevant: pd.DataFrame) -> list[Blackout]:
        """Whole New York days containing an FOMC event.

        Off by default. The record flags FOMC separately rather than saying it
        blocks the day, and blocking a whole day is a large claim to make on
        behalf of a strategy nobody has tested through one.
        """
        lowered = relevant["event"].str.lower()
        is_fomc = lowered.apply(lambda n: any(w in n for w in FOMC_KEYWORDS))
        days = []
        for row in relevant.loc[is_fomc].itertuples():
            local = row.time.tz_convert(MARKET_TZ).normalize()
            days.append(
                Blackout(
                    start=local.tz_convert("UTC"),
                    end=(local + pd.Timedelta(days=1)).tz_convert("UTC"),
                    event=f"{row.event} (whole day)",
                    currency=row.currency,
                    impact="high",
                    at=row.time,
                )
            )
        return days

    def blocked_at(self, moment: pd.Timestamp) -> Blackout | None:
        """The blackout covering ``moment``, if any. For the live loop."""
        moment = pd.Timestamp(moment)
        for blackout in self.blackouts:
            if blackout.covers(moment):
                return blackout
            if blackout.start > moment:
                break  # sorted, so nothing later can cover this moment
        return None

    def mask(self, index: pd.DatetimeIndex) -> np.ndarray:
        """True where entries are blocked, for a whole index at once.

        Built with two searchsorted passes rather than a loop over windows: a
        backtest asks this of every candle, and a per candle scan over a year
        of releases is slower than everything else in the engine put together.
        """
        blocked = np.zeros(len(index), dtype=bool)
        if not self.blackouts:
            return blocked

        values = index.tz_convert("UTC").tz_localize(None).to_numpy()
        starts = np.array(
            [b.start.tz_convert("UTC").tz_localize(None).to_datetime64() for b in self.blackouts]
        )
        ends = np.array(
            [b.end.tz_convert("UTC").tz_localize(None).to_datetime64() for b in self.blackouts]
        )

        # Windows can overlap, so count how many have opened and how many have
        # closed by each moment. Inside at least one window means blocked.
        opened = np.searchsorted(np.sort(starts), values, side="right")
        closed = np.searchsorted(np.sort(ends), values, side="left")
        return opened > closed

    def summary(self) -> str:
        """What the gate will do, for the plan message and the report."""
        if self.is_empty:
            return (
                "No calendar loaded, so nothing is gated. This is not the same "
                "as a quiet week: see docs/news.md for where to get one."
            )
        lines = [
            f"{len(self.blackouts)} blackout windows for {self.instrument} "
            f"({', '.join(self.currencies)})",
            f"{self.minutes_before} minutes before to {self.minutes_after} after "
            f"each high impact release",
        ]
        for blackout in self.blackouts[:10]:
            lines.append(f"  {blackout}")
        if len(self.blackouts) > 10:
            lines.append(f"  ... and {len(self.blackouts) - 10} more")
        return "\n".join(lines)


def gated_minutes(gate: NewsGate, index: pd.DatetimeIndex) -> float:
    """The share of an index the gate blocks.

    Worth printing next to any backtest that used a gate. A gate blocking a
    third of the session is not a filter, it is a different strategy, and the
    comparison to an ungated run is no longer like for like.
    """
    if len(index) == 0:
        return 0.0
    return float(gate.mask(index).mean())
