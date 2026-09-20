"""The Silver Bullet, encoded.

From the project record:

    Inside a one hour window, sweep then FVG toward draw on liquidity.
    Entry: limit at first FVG in window. Stop: beyond FVG origin swing.
    Target: nearest liquidity, minimum 2R.

Three ICT windows, New York time: 03:00 to 04:00 (London), 10:00 to 11:00
(New York AM) and 14:00 to 15:00 (New York PM).

Where the record is loose, the choice is a parameter rather than a silent
decision, because the whole point of Phase 2 is finding out whether the rule
has an edge, not proving it does. Each one is named in :class:`SilverBulletConfig`.

The sequence at every one minute candle inside a window:

1. **Draw on liquidity.** The nearest unswept pool as at now. Long if it sits
   above price, short if below. No draw, no trade.
2. **Sweep.** A liquidity sweep against the draw must have happened inside
   this window, taking the stops before the move toward the draw.
3. **Fair value gap.** The first gap formed after that sweep, pointing at the
   draw. That is the limit price.
4. **Stop** beyond the sweep extreme plus a buffer, so the trade is wrong if
   price goes back through the liquidity it just took.
5. **Target** the draw, and only if that is at least 2R away.

Everything it reads is filtered to what was knowable at the time.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..analysis import Analysis
from ..detectors.fvg import unmitigated
from ..detectors.liquidity import unswept
from ..timeframes.lookahead import knowable_at
from ..timeframes.sessions import SILVER_BULLET_WINDOWS, in_window, window_by_name
from .broker import Order


@dataclass(frozen=True)
class SilverBulletConfig:
    """Every loose end in the written rule, as a parameter to test."""

    #: Which windows to trade. All three by default.
    windows: tuple[str, ...] = SILVER_BULLET_WINDOWS
    #: Stop goes this multiple of the sweep's own size beyond its extreme.
    stop_buffer_atr: float = 0.1
    #: A trade must offer at least this reward to risk, or it is skipped.
    minimum_r: float = 2.0
    #: An unfilled limit order dies this many minutes after it is placed.
    order_life_minutes: int = 20
    #: The timeframe the entry gap is read from.
    entry_timeframe: str = "1m"
    #: The timeframe the draw on liquidity is read from.
    draw_timeframe: str = "1h"


@dataclass
class Setup:
    """A tradeable setup, with the reasoning kept for the journal."""

    direction: str
    limit: float
    stop: float
    target: float
    reason: str
    expires_at: pd.Timestamp | None = None


def window_bounds(
    stamp: pd.Timestamp, windows: tuple[str, ...]
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """The start and end of the Silver Bullet window ``stamp`` falls in."""
    index = pd.DatetimeIndex([stamp])
    for name in windows:
        window = window_by_name(name)
        if bool(in_window(index, window).iloc[0]):
            ny = index.tz_convert("America/New_York")[0]
            start = ny.normalize() + pd.Timedelta(
                hours=window.start.hour, minutes=window.start.minute
            )
            end = ny.normalize() + pd.Timedelta(
                hours=window.end.hour, minutes=window.end.minute
            )
            return start.tz_convert("UTC"), end.tz_convert("UTC")
    return None


class SilverBullet:
    """Builds Silver Bullet orders from what was knowable at each candle."""

    name = "silver_bullet"

    def __init__(
        self,
        entry: Analysis,
        draw: Analysis,
        config: SilverBulletConfig | None = None,
    ) -> None:
        self.entry = entry
        self.draw = draw
        self.config = config or SilverBulletConfig()

    def draw_on_liquidity(
        self, now: pd.Timestamp, price: float
    ) -> tuple[str, float] | None:
        """The nearest unswept pool as at ``now``, and which way it points.

        Two filters, and both are needed. ``unswept`` drops pools that have
        already been taken, but it compares against ``created_at``, which is a
        candle *open* time: on the 1 hour draw timeframe that candle does not
        close for another hour, so on its own it leaks up to 59 minutes of the
        future. ``knowable_at`` closes that.
        """
        pools = unswept(self.draw.pools, now)
        pools = knowable_at(
            pools, self.config.draw_timeframe, now, column="created_at"
        )
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

        # Whichever pool is closer is the one price is being drawn to.
        if (nearest_above - price) <= (price - nearest_below):
            return "long", float(nearest_above)
        return "short", float(nearest_below)

    def find_setup(self, now: pd.Timestamp, candle: pd.Series) -> Setup | None:
        """The setup live at ``now``, or None."""
        bounds = window_bounds(now, self.config.windows)
        if bounds is None:
            return None
        window_start, window_end = bounds

        price = float(candle["close"])
        drawn = self.draw_on_liquidity(now, price)
        if drawn is None:
            return None
        direction, target = drawn

        # A sweep inside this window, against the direction we want to go.
        sweeps = knowable_at(
            self.entry.sweeps, self.config.entry_timeframe, now, column="closed_back_at"
        )
        sweeps = sweeps.loc[sweeps["time"] >= window_start]
        # Going long means the stops taken were below: a sell side sweep.
        wanted_side = "sell" if direction == "long" else "buy"
        sweeps = sweeps.loc[sweeps["side"] == wanted_side]
        if sweeps.empty:
            return None
        sweep = sweeps.iloc[-1]

        # The first gap formed after that sweep, pointing at the draw, that
        # price has not already traded back into. A mitigated gap is spent:
        # resting a limit order at a level price has been through and left is
        # waiting for an imbalance that no longer exists.
        gaps = knowable_at(self.entry.fvgs, self.config.entry_timeframe, now)
        gaps = unmitigated(gaps, now)
        gaps = gaps.loc[gaps["time"] > sweep["closed_back_at"]]
        wanted_gap = "bullish" if direction == "long" else "bearish"
        gaps = gaps.loc[gaps["direction"] == wanted_gap]
        if gaps.empty:
            return None
        gap = gaps.iloc[0]

        # Enter at the far edge of the gap, where price has to come back to.
        limit = float(gap["top"]) if direction == "long" else float(gap["bottom"])

        # Already through it: the move went without us.
        if direction == "long" and price < limit:
            return None
        if direction == "short" and price > limit:
            return None

        buffer = abs(float(sweep["extreme"]) - float(sweep["pool_price"]))
        buffer *= self.config.stop_buffer_atr
        stop = (
            float(sweep["extreme"]) - buffer
            if direction == "long"
            else float(sweep["extreme"]) + buffer
        )

        risk = abs(limit - stop)
        if risk <= 0:
            return None
        reward = abs(target - limit)
        if reward < risk * self.config.minimum_r:
            return None

        return Setup(
            direction=direction,
            limit=limit,
            stop=stop,
            target=target,
            expires_at=min(
                now + pd.Timedelta(minutes=self.config.order_life_minutes),
                window_end,
            ),
            reason=(
                f"{wanted_side} sweep at {sweep['pool_price']:.5f} "
                f"then {wanted_gap} fvg, draw {target:.5f}, "
                f"{reward / risk:.1f}R"
            ),
        )

    def to_order(
        self, now: pd.Timestamp, setup: Setup, size: float
    ) -> Order:
        return Order(
            placed_at=now,
            direction=setup.direction,
            limit=setup.limit,
            stop=setup.stop,
            target=setup.target,
            size=size,
            # An order dies at the end of its window even if its life has not
            # run out. A Silver Bullet entry belongs inside the hour; filling
            # one at lunchtime would be a different strategy wearing the name.
            expires_at=setup.expires_at
            or min(
                now + pd.Timedelta(minutes=self.config.order_life_minutes),
                window_bounds(now, self.config.windows)[1],
            ),
            reason=setup.reason,
        )
