"""The two news playbooks, kept apart from the ICT models on purpose.

The record is explicit that news trading runs as its own strategy so each is
tested on its own record. They are :class:`~ict.backtest.models.BaseModel`
subclasses so the same engine, broker, costs and risk manager apply, but they
are never mixed into the ICT rankings.

**Playbook A, directional.** Before the release, the expected direction is the
sign of forecast minus previous. After it, the surprise confirms or cancels
that. Entry only if the first 1 minute candle closes in the surprise direction
with the spread back to normal.

**Playbook B, spike correction.** After a spike larger than K times the
pre-release ATR, wait for it to stall, then fade toward its 50% level. In ICT
terms the spike is a liquidity sweep, so entry is after a market structure
shift on the 1 minute chart and a return into the gap the spike left. Stop
beyond the spike extreme, target the 50% retracement.

**Costs here are not the costs elsewhere.** The record models spread and
slippage at three to five times normal for the first sixty seconds, and that is
not a detail: a news strategy tested at normal spread is testing a market that
does not exist at 08:30. :class:`NewsCostModel` applies the multiplier, and any
result produced without it should be thrown away.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..backtest.costs import CostModel
from ..backtest.models import BaseModel, ModelConfig
from ..backtest.strategy import Context, Setup
from ..detectors.atr import atr
from .calendar import Event


@dataclass(frozen=True)
class NewsCostModel(CostModel):
    """Normal costs, multiplied for the seconds after a release.

    Without this a news backtest fills at a spread the broker was not showing.
    The multiplier decays back to normal over ``widened_seconds`` rather than
    stepping, because the book refills gradually.
    """

    spike_multiple: float = 4.0
    widened_seconds: int = 60
    release_times: tuple[pd.Timestamp, ...] = ()

    def multiplier_at(self, moment: pd.Timestamp) -> float:
        """How much wider the spread is than normal at ``moment``."""
        if not self.release_times:
            return 1.0
        moment = pd.Timestamp(moment)
        for release in self.release_times:
            elapsed = (moment - release).total_seconds()
            if 0 <= elapsed <= self.widened_seconds:
                decay = 1.0 - (elapsed / self.widened_seconds)
                return 1.0 + (self.spike_multiple - 1.0) * decay
        return 1.0

    def spread_at(self, candle: pd.Series) -> float:
        base = super().spread_at(candle)
        name = getattr(candle, "name", None)
        return base * self.multiplier_at(name) if name is not None else base


@dataclass
class NewsConfig(ModelConfig):
    """Settings both playbooks share, plus one each."""

    #: How long after a release a setup may still be taken.
    window_minutes: int = 30
    #: A surprise smaller than this, in scaled units, is not a surprise.
    minimum_surprise: float = 0.5
    #: Playbook B: a spike must exceed this multiple of the pre-release ATR.
    spike_atr_multiple: float = 2.0
    #: Playbook B: how long the spike must stall before it is faded.
    stall_candles: int = 2


class NewsPlaybook(BaseModel):
    """Shared plumbing: which release is live, and when it stops being live."""

    def __init__(
        self,
        context: Context,
        config: NewsConfig | None = None,
        events: list[Event] | None = None,
    ) -> None:
        super().__init__(context, config or NewsConfig())
        # Only releases with an actual figure can be traded: one without is a
        # scheduled event, not a result.
        self.events = sorted(
            [e for e in (events or []) if e.is_high_impact and e.actual is not None],
            key=lambda e: e.time,
        )

    def live_event(self, now: pd.Timestamp) -> Event | None:
        """The release this moment belongs to, if any.

        Strictly after the release time: a candle stamped at the release minute
        is the one the release happened in, and trading it means trading on a
        figure that was not out when the candle opened.
        """
        window = pd.Timedelta(minutes=self.config.window_minutes)
        for event in self.events:
            if event.time < now <= event.time + window:
                return event
        return None

    def candles_since(self, event: Event, now: pd.Timestamp) -> pd.DataFrame:
        """Entry timeframe candles from the release to now, inclusive."""
        candles = self.context.entry.candles
        return candles.loc[(candles.index >= event.time) & (candles.index <= now)]


class DirectionalPlaybook(NewsPlaybook):
    """Playbook A: trade the surprise, once price agrees with it."""

    name = "news_directional"

    def find_setup(self, now: pd.Timestamp, candle: pd.Series) -> Setup | None:
        event = self.live_event(now)
        if event is None:
            return None

        surprise = self.scaled_surprise(event)
        if surprise is None or abs(surprise) < self.config.minimum_surprise:
            return None

        recent = self.candles_since(event, now)
        if len(recent) < 1:
            return None

        # The first candle after the release has to close in the surprise's
        # direction. A surprise the market ignored is not a trade, whatever
        # the number said.
        first = recent.iloc[0]
        moved_up = float(first["close"]) > float(first["open"])
        if (surprise > 0) != moved_up:
            return None

        direction = "long" if surprise > 0 else "short"
        price = float(candle["close"])
        extreme = (
            float(recent["low"].min()) if direction == "long"
            else float(recent["high"].max())
        )
        buffer = abs(price - extreme) * self.config.stop_buffer
        stop = extreme - buffer if direction == "long" else extreme + buffer
        risk = abs(price - stop)
        if risk <= 0:
            return None
        target = (
            price + risk * self.config.minimum_r if direction == "long"
            else price - risk * self.config.minimum_r
        )

        return self._finish(
            now, direction, price, stop, target,
            f"news directional: {event.name} surprise {surprise:+.2f} scaled",
            price,
        )

    def scaled_surprise(self, event: Event) -> float | None:
        """The surprise in units of this event's own historical spread."""
        raw = event.surprise
        if raw is None:
            return None
        history = [
            abs(e.surprise)
            for e in self.events
            if e.name.lower() == event.name.lower()
            and e.time < event.time
            and e.surprise is not None
        ]
        if len(history) < 4:
            return None  # too little history to scale by, so no trade
        scale = sum(history) / len(history)
        return raw / scale if scale > 0 else None


class SpikeCorrectionPlaybook(NewsPlaybook):
    """Playbook B: fade a spike that has stopped going."""

    name = "news_spike_correction"

    def find_setup(self, now: pd.Timestamp, candle: pd.Series) -> Setup | None:
        event = self.live_event(now)
        if event is None:
            return None

        recent = self.candles_since(event, now)
        if len(recent) < self.config.stall_candles + 2:
            return None

        before = self.context.entry.candles.loc[
            self.context.entry.candles.index < event.time
        ].tail(60)
        if len(before) < 20:
            return None
        pre_atr = float(atr(before, period=14).iloc[-1])
        if not pre_atr or pre_atr != pre_atr:
            return None

        opening = float(recent.iloc[0]["open"])
        high, low = float(recent["high"].max()), float(recent["low"].min())
        up, down = high - opening, opening - low
        spike_up = up >= down

        size = up if spike_up else down
        if size < pre_atr * self.config.spike_atr_multiple:
            return None

        # It has to have stopped. A spike still extending is a trend, and
        # fading a trend because it started as a spike is how this playbook
        # loses money.
        stall = recent.tail(self.config.stall_candles)
        if spike_up and float(stall["high"].max()) >= high:
            return None
        if not spike_up and float(stall["low"].min()) <= low:
            return None

        # The record treats the spike as a liquidity sweep, so a shift has to
        # confirm the turn before it is faded.
        shifts = self.context.shifts_by(now)
        if shifts.empty:
            return None
        shift = shifts.iloc[-1]
        if pd.Timestamp(shift["time"]) < event.time:
            return None
        wanted = "down" if spike_up else "up"
        if shift["direction"] != wanted:
            return None

        direction = "short" if spike_up else "long"
        extreme = high if spike_up else low
        midpoint = (high + low) / 2.0

        gaps = self.context.live_gaps(now, direction, since=event.time)
        price = float(candle["close"])
        limit = (
            float(gaps.iloc[0]["bottom" if direction == "short" else "top"])
            if not gaps.empty
            else price
        )

        buffer = abs(extreme - midpoint) * self.config.stop_buffer
        stop = extreme + buffer if direction == "short" else extreme - buffer

        return self._finish(
            now, direction, limit, stop, midpoint,
            f"news spike correction: {event.name}, spike {size / pre_atr:.1f} ATR",
            price,
        )


#: The playbooks, kept in their own registry so they never appear in an ICT
#: ranking by accident. They are a different strategy with a different record.
PLAYBOOKS = {
    DirectionalPlaybook.name: DirectionalPlaybook,
    SpikeCorrectionPlaybook.name: SpikeCorrectionPlaybook,
}
