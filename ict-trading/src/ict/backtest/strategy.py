"""What every ICT model has in common.

The six models in the project record differ in what they look for and when,
but they all answer the same question at each candle: is there a setup here,
and if so where are the entry, stop and target. That question is this module's
:class:`Strategy` protocol, and the engine knows nothing else about them.

The shared parts live here too, because they are the same reasoning in every
model and were worth writing once: the market context as at a point in time,
the draw on liquidity, and the daily bias that follows from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from ..analysis import Analysis
from ..detectors.fvg import unmitigated
from ..detectors.liquidity import unswept
from ..timeframes.lookahead import knowable_at


@dataclass
class Setup:
    """A tradeable setup, with the reasoning kept for the journal."""

    direction: str  # "long" or "short"
    limit: float
    stop: float
    target: float
    reason: str
    expires_at: pd.Timestamp | None = None

    @property
    def risk(self) -> float:
        return abs(self.limit - self.stop)

    @property
    def reward(self) -> float:
        return abs(self.target - self.limit)

    @property
    def reward_to_risk(self) -> float:
        return self.reward / self.risk if self.risk > 0 else 0.0


class Strategy(Protocol):
    """A model the engine can trade.

    ``name`` labels it in reports. ``tradeable_at`` lets a model that only
    trades certain hours skip the rest cheaply. ``find_setup`` is the model.
    """

    name: str

    def tradeable_at(self, now: pd.Timestamp) -> bool: ...

    def find_setup(self, now: pd.Timestamp, candle: pd.Series) -> Setup | None: ...

    def order_life(self) -> pd.Timedelta: ...


@dataclass
class Context:
    """The detector output a model reads, and the timeframes it came from.

    Built once per run and shared by every model, because analysing the same
    candles six times over is the slowest thing the engine could do.
    """

    entry: Analysis
    draw: Analysis
    entry_timeframe: str = "1m"
    draw_timeframe: str = "1h"

    def sweeps_by(self, now: pd.Timestamp, since: pd.Timestamp | None = None):
        """Sweeps confirmed by ``now``, optionally only after ``since``."""
        sweeps = knowable_at(
            self.entry.sweeps, self.entry_timeframe, now, column="closed_back_at"
        )
        if since is not None and not sweeps.empty:
            sweeps = sweeps.loc[sweeps["time"] >= since]
        return sweeps

    def shifts_by(self, now: pd.Timestamp, since: pd.Timestamp | None = None):
        """Market structure shifts knowable at ``now``."""
        shifts = knowable_at(self.entry.shifts, self.entry_timeframe, now)
        if since is not None and not shifts.empty:
            shifts = shifts.loc[shifts["time"] >= since]
        return shifts

    def live_gaps(self, now: pd.Timestamp, direction: str, since=None):
        """Gaps knowable at ``now``, still unmitigated, pointing ``direction``.

        A mitigated gap is spent: resting an order at a level price has been
        through and left is waiting for an imbalance that no longer exists.
        """
        gaps = knowable_at(self.entry.fvgs, self.entry_timeframe, now)
        gaps = unmitigated(gaps, now)
        if gaps.empty:
            return gaps
        wanted = "bullish" if direction == "long" else "bearish"
        gaps = gaps.loc[gaps["direction"] == wanted]
        if since is not None and not gaps.empty:
            gaps = gaps.loc[gaps["time"] > since]
        return gaps

    def level(self, now: pd.Timestamp, name: str) -> float | None:
        """A session level for the current New York day, if it is finished.

        ``available_from`` is what makes this safe: the Asian range is not a
        level until Asia has closed, and the previous day's high is not one
        until that day ended.
        """
        levels = self.entry.levels
        if levels is None or levels.empty:
            return None
        ready = levels.loc[levels["available_from"] <= now]
        matching = ready.loc[ready["name"] == name]
        if matching.empty:
            return None
        return float(matching.iloc[-1]["price"])

    def pools(self, now: pd.Timestamp):
        """Unswept liquidity pools on the draw timeframe, as at ``now``.

        Both filters are needed. ``unswept`` compares against ``created_at``,
        which is a candle open time, so on a 1 hour timeframe it leaks up to
        59 minutes of future on its own.
        """
        live = unswept(self.draw.pools, now)
        return knowable_at(live, self.draw_timeframe, now, column="created_at")

    def draw_on_liquidity(
        self, now: pd.Timestamp, price: float
    ) -> tuple[str, float] | None:
        """The nearest unswept pool as at ``now``, and which way it points."""
        pools = self.pools(now)
        if pools.empty:
            return None

        above = pools.loc[(pools["side"] == "buy") & (pools["price"] > price)]
        below = pools.loc[(pools["side"] == "sell") & (pools["price"] < price)]

        nearest_above = above["price"].min() if not above.empty else None
        nearest_below = below["price"].max() if not below.empty else None

        if nearest_above is None and nearest_below is None:
            return None
        if nearest_above is None:
            return "short", float(nearest_below)
        if nearest_below is None:
            return "long", float(nearest_above)

        if (nearest_above - price) <= (price - nearest_below):
            return "long", float(nearest_above)
        return "short", float(nearest_below)

    def opposing_pool(
        self, now: pd.Timestamp, price: float, direction: str
    ) -> float | None:
        """The pool a move in ``direction`` is heading for."""
        pools = self.pools(now)
        if pools.empty:
            return None
        if direction == "long":
            above = pools.loc[(pools["side"] == "buy") & (pools["price"] > price)]
            return float(above["price"].min()) if not above.empty else None
        below = pools.loc[(pools["side"] == "sell") & (pools["price"] < price)]
        return float(below["price"].max()) if not below.empty else None


def build_context(
    candles: pd.DataFrame,
    detector_config=None,
    draw_timeframe: str = "1h",
) -> Context:
    """Analyse once, for every model to share."""
    from ..analysis import analyse
    from ..timeframes.resample import resample

    # Levels are wanted: Judas and Power of Three both read the midnight open
    # and the Asian range off them.
    entry = analyse(
        candles, timeframe="1m", config=detector_config, with_levels=True
    )
    draw = analyse(
        resample(candles, draw_timeframe),
        timeframe=draw_timeframe,
        config=detector_config,
    )
    return Context(entry=entry, draw=draw, draw_timeframe=draw_timeframe)
