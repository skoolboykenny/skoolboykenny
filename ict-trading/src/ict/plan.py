"""The daily plan: what the system intends to do before the day starts.

From the record, run once a day around 19:30 New York, just before Asia opens.
Seven steps: refresh the data, set the bias, map the path to it, mark the
levels, load the news, check the account, and send a short message.

It is a read only routine. It places nothing and changes nothing, so it can be
run at any time, on a practice account or with no account at all, and the worst
it can do is print something wrong. That makes it the cheapest way to see what
the system thinks, which is the point: a strategy you cannot inspect before it
trades is one you will only understand afterwards.

The bias here is the same `draw_on_liquidity` the models use, read off the 4
hour frame. It is deliberately not a second opinion: a plan that disagreed with
the engine would be describing a system nobody is running.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .analysis import analyse
from .backtest.strategy import Context
from .config import MARKET_TZ, Config
from .detectors.fvg import unmitigated
from .timeframes.resample import resample
from .timeframes.sessions import KILL_ZONES, market_date, window_by_name

#: Levels worth naming in a plan, in the order a person reads them.
PLAN_LEVELS = (
    "midnight_open",
    "previous_day_high",
    "previous_day_low",
    "previous_week_high",
    "previous_week_low",
    "asian_high",
    "asian_low",
)


@dataclass
class Zone:
    """A gap or order block between price and the draw."""

    kind: str
    direction: str
    top: float
    bottom: float
    at: pd.Timestamp

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2.0

    def __str__(self) -> str:
        return f"{self.kind} {self.bottom:.5f} to {self.top:.5f}"


@dataclass
class DailyPlan:
    """What the system intends, and why."""

    at: pd.Timestamp
    instrument: str
    price: float
    bias: str = "no trade"
    draw: float | None = None
    reason: str = ""
    zones: list[Zone] = field(default_factory=list)
    levels: dict[str, float] = field(default_factory=dict)
    blackouts: list[str] = field(default_factory=list)
    windows: list[str] = field(default_factory=list)
    account: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: Whether a calendar was supplied at all. An empty `blackouts` means two
    #: different things, a quiet day and no calendar, and they must not read
    #: the same.
    has_calendar: bool = False

    @property
    def is_no_trade(self) -> bool:
        return self.bias == "no trade"

    def message(self) -> str:
        """The short phone message from the record.

        One line, because it is read on a phone at half past one in the
        morning. Everything else belongs in the full report.
        """
        local = self.at.tz_convert(MARKET_TZ)
        if self.is_no_trade:
            return (
                f"{self.instrument} {local:%a %d %b}: no trade. {self.reason}"
            )
        head = f"{self.instrument} bias {self.bias}, draw at {self.draw:.5f}"
        if self.blackouts:
            head += f". {self.blackouts[0]}"
        return head

    def report(self) -> str:
        """The whole plan, for the terminal and the daily log."""
        local = self.at.tz_convert(MARKET_TZ)
        lines = [
            f"Daily plan: {self.instrument}",
            "=" * 66,
            f"{local:%A %d %B %Y, %H:%M} New York  ({self.at:%H:%M} UTC)",
            f"price {self.price:.5f}",
            "",
            "Bias",
            "-" * 66,
        ]
        if self.is_no_trade:
            lines.append(f"  NO TRADE: {self.reason}")
        else:
            lines.append(f"  {self.bias.upper()}, draw on liquidity at {self.draw:.5f}")
            lines.append(f"  {self.reason}")

        if self.zones:
            lines += ["", "Path to the draw", "-" * 66]
            for zone in self.zones[:8]:
                lines.append(f"  {zone}")
            lines.append(
                "  Only these zones count for entries. Price reaching the draw"
            )
            lines.append("  by another route is a move the plan did not describe.")

        if self.levels:
            lines += ["", "Levels", "-" * 66]
            for name in PLAN_LEVELS:
                if name in self.levels:
                    lines.append(f"  {name:<22}{self.levels[name]:.5f}")

        lines += ["", "News", "-" * 66]
        if self.blackouts:
            for blackout in self.blackouts[:6]:
                lines.append(f"  {blackout}")
        elif self.has_calendar:
            lines.append("  No high impact release for this pair in the next day.")
        else:
            lines.append("  No calendar loaded, so nothing is gated today.")
            lines.append("  That is ignorance of releases, not absence of them.")

        if self.windows:
            lines += ["", "Windows today", "-" * 66]
            for window in self.windows:
                lines.append(f"  {window}")

        lines += ["", "Account", "-" * 66]
        if self.account:
            for key, value in self.account.items():
                shown = f"{value:,.2f}" if isinstance(value, float) else value
                lines.append(f"  {key:<22}{shown}")
        else:
            lines.append("  No broker connected. Nothing will be placed.")

        if self.warnings:
            lines += ["", "Warnings", "-" * 66]
            for warning in self.warnings:
                lines.append(f"  {warning}")

        lines += ["", "-" * 66, self.message()]
        return "\n".join(lines)


def build_plan(
    candles: pd.DataFrame,
    instrument: str = "EUR_USD",
    now: pd.Timestamp | None = None,
    news_gate=None,
    broker=None,
    detector_config: Config | None = None,
    bias_timeframe: str = "4h",
) -> DailyPlan:
    """Run the seven steps and return the plan.

    ``now`` defaults to the last candle rather than the wall clock, so a plan
    can be rebuilt for any past day and will say what it would have said then.
    Everything is read through the same point in time accessors the engine
    uses, so a plan cannot see further than the engine could.
    """
    if candles.empty:
        raise ValueError("cannot plan from an empty series")

    now = pd.Timestamp(now) if now is not None else candles.index[-1]
    visible = candles.loc[candles.index <= now]
    if visible.empty:
        raise ValueError(f"no candles at or before {now}")

    price = float(visible["close"].iloc[-1])
    plan = DailyPlan(at=now, instrument=instrument, price=price)

    # Step 1 and 2: refresh, then read the bias off the higher timeframe.
    entry = analyse(visible, config=detector_config, with_levels=True)
    higher = resample(visible, bias_timeframe)
    if len(higher) < 2:
        plan.reason = f"fewer than two {bias_timeframe} candles of history"
        return plan

    draw_analysis = analyse(higher, config=detector_config)
    context = Context(
        entry=entry, draw=draw_analysis, entry_timeframe="1m",
        draw_timeframe=bias_timeframe,
    )

    drawn = context.draw_on_liquidity(now, price)
    if drawn is None:
        plan.reason = "no unswept pool on either side, so no draw to trade toward"
        return plan

    direction, target = drawn
    plan.bias = direction
    plan.draw = target
    distance = abs(target - price)
    plan.reason = (
        f"nearest unswept {bias_timeframe} pool is {distance:.5f} "
        f"{'above' if direction == 'long' else 'below'}"
    )

    # Step 3: only zones between price and the draw count.
    plan.zones = _path_to_draw(context, now, price, target, direction)
    if not plan.zones:
        plan.warnings.append(
            "No unmitigated gap between price and the draw. The bias stands, "
            "but no entry zone is mapped."
        )

    # Step 4: the levels that are finished and safe to use.
    plan.levels = _levels(context, now)

    # Step 5: the day's releases.
    if news_gate is not None and not news_gate.is_empty:
        plan.has_calendar = True
        day_end = now + pd.Timedelta(days=1)
        plan.blackouts = [
            str(b) for b in news_gate.blackouts if now <= b.start <= day_end
        ]
        if news_gate.blocked_at(now) is not None:
            plan.warnings.append("A blackout is active right now.")

    plan.windows = _windows_today(now)

    # Step 6: the account, if one is connected.
    if broker is not None:
        plan.account, account_warnings = _account(broker)
        plan.warnings.extend(account_warnings)
        if account_warnings:
            plan.bias = "no trade"
            plan.reason = account_warnings[0]

    return plan


def _path_to_draw(
    context: Context, now: pd.Timestamp, price: float, target: float, direction: str
) -> list[Zone]:
    """Unmitigated gaps lying between price and the draw, nearest first."""
    gaps = context.live_gaps(now, direction)
    if gaps.empty:
        return []

    low, high = min(price, target), max(price, target)
    zones = []
    for row in gaps.itertuples():
        top, bottom = float(row.top), float(row.bottom)
        if bottom > high or top < low:
            continue  # not on the way
        zones.append(
            Zone(kind="fair value gap", direction=direction, top=top,
                 bottom=bottom, at=pd.Timestamp(row.time))
        )

    zones.sort(key=lambda z: abs(z.midpoint - price))
    return zones


def _levels(context: Context, now: pd.Timestamp) -> dict[str, float]:
    """The named levels that are finished at ``now``."""
    found = {}
    for name in PLAN_LEVELS:
        value = context.level(now, name)
        if value is not None:
            found[name] = value
    return found


def _windows_today(now: pd.Timestamp) -> list[str]:
    """The kill zones, as New York clock times, for the plan's day."""
    local = now.tz_convert(MARKET_TZ)
    lines = []
    for window in KILL_ZONES:
        start = f"{window.start.hour:02d}:{window.start.minute:02d}"
        end = f"{window.end.hour:02d}:{window.end.minute:02d}"
        marker = " <- now" if _in_window_now(local, window) else ""
        lines.append(f"{window.name:<24}{start} to {end} New York{marker}")
    return lines


def _in_window_now(local: pd.Timestamp, window) -> bool:
    minutes = local.hour * 60 + local.minute
    start = window.start.hour * 60 + window.start.minute
    end = window.end.hour * 60 + window.end.minute
    if window.crosses_midnight:
        return minutes >= start or minutes < end
    return start <= minutes < end


def _account(broker) -> tuple[dict, list[str]]:
    """Balance, positions and whether anything is already blocking trading."""
    warnings: list[str] = []
    try:
        summary = broker.account()
    except Exception as error:
        return {}, [f"broker unreachable: {error}"]

    state = {
        "balance": float(summary.get("balance", 0.0)),
        "equity (NAV)": float(summary.get("NAV", summary.get("balance", 0.0))),
        "unrealised": float(summary.get("unrealizedPL", 0.0)),
        "open positions": int(summary.get("openPositionCount", 0)),
        "pending orders": int(summary.get("pendingOrderCount", 0)),
    }

    if state["open positions"]:
        warnings.append(
            f"{state['open positions']} position already open. The loop will "
            "not enter while one is live."
        )
    if state["equity (NAV)"] <= 0:
        warnings.append("Account equity is zero or negative.")
    return state, warnings
