"""The ICT models from the project record, each as its own strategy.

Six models, encoded separately so each can be tested and ranked on its own
before any are combined. They share the detector library and the context, so a
difference in results is a difference in the rule rather than in the plumbing.

Where the record is loose, the choice is a parameter rather than a silent
decision. None of these numbers has been checked against a hand marked chart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..timeframes.sessions import (
    KILL_ZONES,
    SILVER_BULLET_WINDOWS,
    in_window,
    window_by_name,
)
from .strategy import Context, Setup


def _in_any(now: pd.Timestamp, names: tuple[str, ...]) -> bool:
    index = pd.DatetimeIndex([now])
    return any(bool(in_window(index, window_by_name(n)).iloc[0]) for n in names)


def _window_bounds(
    now: pd.Timestamp, names: tuple[str, ...]
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    index = pd.DatetimeIndex([now])
    for name in names:
        window = window_by_name(name)
        if bool(in_window(index, window).iloc[0]):
            ny = index.tz_convert("America/New_York")[0].normalize()
            start = ny + pd.Timedelta(
                hours=window.start.hour, minutes=window.start.minute
            )
            end = ny + pd.Timedelta(hours=window.end.hour, minutes=window.end.minute)
            if window.crosses_midnight:
                end += pd.Timedelta(days=1)
            return start.tz_convert("UTC"), end.tz_convert("UTC")
    return None


@dataclass
class ModelConfig:
    """Settings every model shares."""

    #: Stop goes this multiple of the move's own size beyond its extreme.
    stop_buffer: float = 0.1
    #: A trade must offer at least this reward to risk.
    minimum_r: float = 2.0
    #: An unfilled limit order dies after this long.
    order_life_minutes: int = 20
    #: Windows the model trades in. Empty means any time.
    windows: tuple[str, ...] = ()


class BaseModel:
    """Shared behaviour: window gating, order life, and the R filter."""

    name = "base"

    def __init__(self, context: Context, config: ModelConfig | None = None) -> None:
        self.context = context
        self.config = config or ModelConfig()

    def tradeable_at(self, now: pd.Timestamp) -> bool:
        if not self.config.windows:
            return True
        return _in_any(now, self.config.windows)

    def tradeable_mask(self, index: pd.DatetimeIndex):
        """The same question for a whole index at once.

        Asking candle by candle costs more than the model does, and the engine
        asks it two hundred thousand times.
        """
        import numpy as np

        if not self.config.windows:
            return np.ones(len(index), dtype=bool)
        mask = np.zeros(len(index), dtype=bool)
        for name in self.config.windows:
            mask |= in_window(index, window_by_name(name)).to_numpy()
        return mask

    def order_life(self) -> pd.Timedelta:
        return pd.Timedelta(minutes=self.config.order_life_minutes)

    def _expiry(self, now: pd.Timestamp) -> pd.Timestamp:
        """Orders die with their window, not hours after it."""
        life = now + self.order_life()
        bounds = _window_bounds(now, self.config.windows) if self.config.windows else None
        return min(life, bounds[1]) if bounds else life

    def _finish(
        self,
        now: pd.Timestamp,
        direction: str,
        limit: float,
        stop: float,
        target: float,
        reason: str,
        price: float,
    ) -> Setup | None:
        """Common last checks: not already through it, and worth the risk."""
        if direction == "long" and price < limit:
            return None
        if direction == "short" and price > limit:
            return None

        # The stop has to sit on the losing side of the entry and the target on
        # the winning side. A long whose gap opened below the swept low would
        # otherwise rest an order that books its loss the moment it fills, and
        # risk being an absolute distance hides it.
        if direction == "long" and not stop < limit < target:
            return None
        if direction == "short" and not target < limit < stop:
            return None

        setup = Setup(
            direction=direction,
            limit=limit,
            stop=stop,
            target=target,
            reason=reason,
            expires_at=self._expiry(now),
        )
        if setup.risk <= 0 or setup.reward_to_risk < self.config.minimum_r:
            return None
        return setup


class SilverBulletModel(BaseModel):
    """Inside a one hour window, a sweep then a gap toward the draw."""

    name = "silver_bullet"

    def __init__(self, context: Context, config: ModelConfig | None = None) -> None:
        super().__init__(context, config or ModelConfig(windows=SILVER_BULLET_WINDOWS))

    def find_setup(self, now: pd.Timestamp, candle: pd.Series) -> Setup | None:
        bounds = _window_bounds(now, self.config.windows)
        if bounds is None:
            return None
        start, _ = bounds

        price = float(candle["close"])
        drawn = self.context.draw_on_liquidity(now, price)
        if drawn is None:
            return None
        direction, target = drawn

        wanted = "sell" if direction == "long" else "buy"
        sweeps = self.context.sweeps_by(now, since=start)
        sweeps = sweeps.loc[sweeps["side"] == wanted]
        if sweeps.empty:
            return None
        sweep = sweeps.iloc[-1]

        gaps = self.context.live_gaps(now, direction, since=sweep["closed_back_at"])
        if gaps.empty:
            return None
        gap = gaps.iloc[0]

        limit = float(gap["top"]) if direction == "long" else float(gap["bottom"])
        extreme = float(sweep["extreme"])
        buffer = abs(extreme - float(sweep["pool_price"])) * self.config.stop_buffer
        stop = extreme - buffer if direction == "long" else extreme + buffer

        return self._finish(
            now, direction, limit, stop, target,
            f"silver bullet: {wanted} sweep then gap toward {target:.5f}", price,
        )


class Mentorship2022Model(BaseModel):
    """Sweep, displacement with a market structure shift, then the gap.

    The difference from the Silver Bullet is the shift: this model will not
    trade a sweep and a gap on their own, it wants structure to have turned
    first, and it trades any kill zone rather than one hour windows.
    """

    name = "mentorship_2022"

    def __init__(self, context: Context, config: ModelConfig | None = None) -> None:
        zones = tuple(w.name for w in KILL_ZONES if not w.name.endswith("silver_bullet"))
        super().__init__(context, config or ModelConfig(windows=zones))

    def find_setup(self, now: pd.Timestamp, candle: pd.Series) -> Setup | None:
        price = float(candle["close"])
        shifts = self.context.shifts_by(now)
        if shifts.empty:
            return None
        shift = shifts.iloc[-1]

        # The shift has to be recent, or this is history rather than a setup.
        if now - pd.Timestamp(shift["time"]) > pd.Timedelta(minutes=60):
            return None

        direction = "long" if shift["direction"] == "up" else "short"
        target = self.context.opposing_pool(now, price, direction)
        if target is None:
            return None

        gaps = self.context.live_gaps(now, direction, since=shift["sweep_time"])
        if gaps.empty:
            return None
        gap = gaps.iloc[0]
        limit = float(gap["top"]) if direction == "long" else float(gap["bottom"])

        sweeps = self.context.sweeps_by(now)
        at_sweep = sweeps.loc[sweeps["time"] == shift["sweep_time"]]
        if at_sweep.empty:
            return None
        extreme = float(at_sweep.iloc[0]["extreme"])
        buffer = abs(price - extreme) * self.config.stop_buffer
        stop = extreme - buffer if direction == "long" else extreme + buffer

        return self._finish(
            now, direction, limit, stop, target,
            f"2022 model: shift {shift['direction']} after sweep, gap entry", price,
        )


@dataclass
class OTEConfig(ModelConfig):
    """Where in the retracement to sit."""

    #: The sweet spot ICT names, as a fraction of the impulse leg.
    entry_retracement: float = 0.705
    #: The leg has to be at least this many candles long to count as impulse.
    minimum_leg_candles: int = 5


class OTEModel(BaseModel):
    """A retracement into 62% to 79% of an impulse leg, entered at 70.5%.

    The leg is taken from the last shift's swing to the extreme reached since,
    so the model only trades after structure has turned rather than measuring
    any move that happens to have direction.
    """

    name = "optimal_trade_entry"

    def __init__(self, context: Context, config: OTEConfig | None = None) -> None:
        super().__init__(context, config or OTEConfig())
        self.config: OTEConfig = self.config  # type: ignore[assignment]

    def find_setup(self, now: pd.Timestamp, candle: pd.Series) -> Setup | None:
        price = float(candle["close"])
        shifts = self.context.shifts_by(now)
        if shifts.empty:
            return None
        shift = shifts.iloc[-1]
        if now - pd.Timestamp(shift["time"]) > pd.Timedelta(hours=4):
            return None

        direction = "long" if shift["direction"] == "up" else "short"
        candles = self.context.entry.candles
        leg = candles.loc[
            (candles.index >= shift["sweep_time"]) & (candles.index <= now)
        ]
        if len(leg) < self.config.minimum_leg_candles:
            return None

        if direction == "long":
            origin = float(leg["low"].min())
            peak = float(leg["high"].max())
        else:
            origin = float(leg["high"].max())
            peak = float(leg["low"].min())

        span = abs(peak - origin)
        if span <= 0:
            return None

        # 70.5% back from the extreme, toward where the leg started.
        limit = (
            peak - span * self.config.entry_retracement
            if direction == "long"
            else peak + span * self.config.entry_retracement
        )
        buffer = span * self.config.stop_buffer
        stop = origin - buffer if direction == "long" else origin + buffer

        target = self.context.opposing_pool(now, price, direction)
        if target is None:
            # No pool to aim at, so project the leg beyond its own extreme.
            target = peak + span if direction == "long" else peak - span

        return self._finish(
            now, direction, limit, stop, target,
            f"OTE: {self.config.entry_retracement:.0%} of a {span:.5f} leg", price,
        )


class PowerOfThreeModel(BaseModel):
    """Accumulation, manipulation, distribution.

    Asia builds the range. London or New York opens by running one side of it,
    which is the manipulation. The trade is the distribution back the other
    way, entered once structure confirms the reversal.
    """

    name = "power_of_three"

    def __init__(self, context: Context, config: ModelConfig | None = None) -> None:
        super().__init__(context, config or ModelConfig(windows=("london", "ny_am")))

    def find_setup(self, now: pd.Timestamp, candle: pd.Series) -> Setup | None:
        high = self.context.level(now, "asian_high")
        low = self.context.level(now, "asian_low")
        if high is None or low is None or high <= low:
            return None

        price = float(candle["close"])
        shifts = self.context.shifts_by(now)
        if shifts.empty:
            return None
        shift = shifts.iloc[-1]
        if now - pd.Timestamp(shift["time"]) > pd.Timedelta(minutes=90):
            return None

        direction = "long" if shift["direction"] == "up" else "short"
        sweeps = self.context.sweeps_by(now)
        at_sweep = sweeps.loc[sweeps["time"] == shift["sweep_time"]]
        if at_sweep.empty:
            return None
        extreme = float(at_sweep.iloc[0]["extreme"])

        # The manipulation has to have run the Asian range, not something else.
        if direction == "long" and extreme > low:
            return None
        if direction == "short" and extreme < high:
            return None

        gaps = self.context.live_gaps(now, direction, since=shift["time"])
        if gaps.empty:
            return None
        gap = gaps.iloc[0]
        limit = float(gap["top"]) if direction == "long" else float(gap["bottom"])

        span = high - low
        buffer = span * self.config.stop_buffer
        stop = extreme - buffer if direction == "long" else extreme + buffer
        # Distribution projects the range from where the manipulation ended.
        target = extreme + span if direction == "long" else extreme - span

        return self._finish(
            now, direction, limit, stop, target,
            f"power of three: Asia {low:.5f} to {high:.5f}, manipulation to "
            f"{extreme:.5f}", price,
        )


class JudasSwingModel(BaseModel):
    """A false move from the midnight open, then the real one.

    The Judas is the push away from the midnight open early in the session.
    The trade is the reversal back through it, targeting the previous day.
    """

    name = "judas_swing"

    def __init__(self, context: Context, config: ModelConfig | None = None) -> None:
        super().__init__(context, config or ModelConfig(windows=("london", "ny_am")))

    def find_setup(self, now: pd.Timestamp, candle: pd.Series) -> Setup | None:
        midnight = self.context.level(now, "midnight_open")
        if midnight is None:
            return None

        price = float(candle["close"])
        shifts = self.context.shifts_by(now)
        if shifts.empty:
            return None
        shift = shifts.iloc[-1]
        if now - pd.Timestamp(shift["time"]) > pd.Timedelta(minutes=90):
            return None

        direction = "long" if shift["direction"] == "up" else "short"
        sweeps = self.context.sweeps_by(now)
        at_sweep = sweeps.loc[sweeps["time"] == shift["sweep_time"]]
        if at_sweep.empty:
            return None
        extreme = float(at_sweep.iloc[0]["extreme"])

        # The Judas ran the wrong side of the midnight open before turning.
        if direction == "long" and extreme > midnight:
            return None
        if direction == "short" and extreme < midnight:
            return None

        target = self.context.level(
            now, "previous_day_high" if direction == "long" else "previous_day_low"
        )
        if target is None:
            return None

        gaps = self.context.live_gaps(now, direction, since=shift["time"])
        if gaps.empty:
            return None
        gap = gaps.iloc[0]
        limit = float(gap["top"]) if direction == "long" else float(gap["bottom"])

        buffer = abs(midnight - extreme) * self.config.stop_buffer
        stop = extreme - buffer if direction == "long" else extreme + buffer

        return self._finish(
            now, direction, limit, stop, target,
            f"judas: {extreme:.5f} against midnight open {midnight:.5f}", price,
        )


@dataclass
class TurtleSoupConfig(ModelConfig):
    """How obvious the level taken has to have been."""

    #: The pool must have been touched this many times to count as obvious.
    minimum_touches: int = 2


class TurtleSoupModel(BaseModel):
    """A sweep of an obvious prior high or low that fails.

    No gap and no shift required: the entry is the close back inside, which is
    what makes it the earliest and the loosest of the models. The discipline
    comes from the level having been obvious, so it wants equal highs or lows
    rather than any swing.
    """

    name = "turtle_soup"

    def __init__(self, context: Context, config: TurtleSoupConfig | None = None) -> None:
        super().__init__(context, config or TurtleSoupConfig())
        self.config: TurtleSoupConfig = self.config  # type: ignore[assignment]

    def find_setup(self, now: pd.Timestamp, candle: pd.Series) -> Setup | None:
        sweeps = self.context.sweeps_by(now)
        if sweeps.empty:
            return None
        sweep = sweeps.iloc[-1]
        if pd.Timestamp(sweep["closed_back_at"]) < now - pd.Timedelta(minutes=5):
            return None

        pools = self.context.pools(now)
        obvious = pools.loc[pools["touches"] >= self.config.minimum_touches]
        if obvious.empty:
            return None

        direction = "long" if sweep["side"] == "sell" else "short"
        price = float(candle["close"])
        extreme = float(sweep["extreme"])

        target = self.context.opposing_pool(now, price, direction)
        if target is None:
            return None

        # Entry is the close back inside, so the limit is where price is.
        limit = float(sweep["pool_price"])
        buffer = abs(limit - extreme) * self.config.stop_buffer
        stop = extreme - buffer if direction == "long" else extreme + buffer

        return self._finish(
            now, direction, limit, stop, target,
            f"turtle soup: failed sweep of {limit:.5f}", price,
        )


class SweepToSweepModel(BaseModel):
    """From one liquidity pool to the opposing one.

    After a sweep and a shift, the target is the nearest unswept pool on the
    other side, on the reading that price moves between pools rather than to
    a fixed multiple of risk.
    """

    name = "sweep_to_sweep"

    def find_setup(self, now: pd.Timestamp, candle: pd.Series) -> Setup | None:
        shifts = self.context.shifts_by(now)
        if shifts.empty:
            return None
        shift = shifts.iloc[-1]
        if now - pd.Timestamp(shift["time"]) > pd.Timedelta(minutes=45):
            return None

        direction = "long" if shift["direction"] == "up" else "short"
        price = float(candle["close"])
        target = self.context.opposing_pool(now, price, direction)
        if target is None:
            return None

        sweeps = self.context.sweeps_by(now)
        at_sweep = sweeps.loc[sweeps["time"] == shift["sweep_time"]]
        if at_sweep.empty:
            return None
        extreme = float(at_sweep.iloc[0]["extreme"])

        gaps = self.context.live_gaps(now, direction, since=shift["sweep_time"])
        limit = (
            (float(gaps.iloc[0]["top"]) if direction == "long"
             else float(gaps.iloc[0]["bottom"]))
            if not gaps.empty
            else price
        )
        buffer = abs(limit - extreme) * self.config.stop_buffer
        stop = extreme - buffer if direction == "long" else extreme + buffer

        return self._finish(
            now, direction, limit, stop, target,
            f"sweep to sweep: {shift['direction']} toward {target:.5f}", price,
        )


#: Every model, by the name it is reported under.
MODELS: dict[str, type[BaseModel]] = {
    SilverBulletModel.name: SilverBulletModel,
    Mentorship2022Model.name: Mentorship2022Model,
    OTEModel.name: OTEModel,
    PowerOfThreeModel.name: PowerOfThreeModel,
    JudasSwingModel.name: JudasSwingModel,
    TurtleSoupModel.name: TurtleSoupModel,
    SweepToSweepModel.name: SweepToSweepModel,
}
