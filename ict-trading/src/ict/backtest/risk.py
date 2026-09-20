"""Position sizing and the limits that stop a bad day becoming a bad month.

These are the risk rules from the project record, enforced in code. In the live
system they sit where the AI layer cannot reach them; here they matter because
a backtest without them reports an equity curve no one would actually have
traded through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class RiskConfig:
    """The limits, all from the project record."""

    #: Fraction of the account risked per trade. 0.5% during testing.
    risk_per_trade: float = 0.005
    #: Hard cap on trades taken per New York day.
    max_trades_per_day: int = 2
    #: Trading stops for the day once this much of the account is lost.
    daily_loss_limit: float = 0.02
    #: One loss ends the session, per the strategy specification.
    one_loss_per_session: bool = True
    #: A drawdown this deep pauses the system for review.
    weekly_drawdown_pause: float = 0.06


def position_size(
    equity: float, risk_fraction: float, stop_distance: float
) -> float:
    """Units to trade so that hitting the stop loses exactly the risk budget.

    Size follows from the stop, never the other way around. A wider stop buys
    fewer units, so every loss is the same size in currency and the R multiples
    in the report are comparable across trades.
    """
    if stop_distance <= 0:
        return 0.0
    return (equity * risk_fraction) / stop_distance


@dataclass
class DayState:
    """What has happened today, for the caps to read."""

    day: date
    trades: int = 0
    losses: int = 0
    realised: float = 0.0


@dataclass
class RiskManager:
    """Applies the limits and sizes each trade."""

    config: RiskConfig
    starting_equity: float
    equity: float = field(init=False)
    peak_equity: float = field(init=False)
    day: DayState | None = field(default=None, init=False)
    paused: bool = field(default=False, init=False)
    blocked: dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.equity = self.starting_equity
        self.peak_equity = self.starting_equity

    def start_day(self, day: date) -> None:
        self.day = DayState(day=day)

    def _block(self, reason: str) -> None:
        self.blocked[reason] = self.blocked.get(reason, 0) + 1

    def may_trade(self) -> bool:
        """Whether a new entry is allowed right now."""
        if self.paused:
            self._block("weekly drawdown pause")
            return False
        if self.day is None:
            return False
        if self.day.trades >= self.config.max_trades_per_day:
            self._block("daily trade cap")
            return False
        if self.day.realised <= -abs(self.config.daily_loss_limit) * self.equity:
            self._block("daily loss limit")
            return False
        if self.config.one_loss_per_session and self.day.losses > 0:
            self._block("one loss per session")
            return False
        return True

    def size_for(self, stop_distance: float) -> float:
        return position_size(self.equity, self.config.risk_per_trade, stop_distance)

    def record(self, net: float) -> None:
        """Book a closed trade and re-check the drawdown pause."""
        self.equity += net
        self.peak_equity = max(self.peak_equity, self.equity)
        if self.day is not None:
            self.day.trades += 1
            self.day.realised += net
            if net < 0:
                self.day.losses += 1

        drawdown = (
            (self.peak_equity - self.equity) / self.peak_equity
            if self.peak_equity > 0
            else 0.0
        )
        if drawdown >= self.config.weekly_drawdown_pause:
            self.paused = True

    def resume(self) -> None:
        """Lift the pause, as a human review would.

        The live system requires a manual restart after a halt. A backtest
        cannot ask anyone, so it resumes at the start of the next week and the
        report says how often that happened: a strategy that trips the pause
        repeatedly is failing, whatever its final equity says.
        """
        self.paused = False
        self.peak_equity = self.equity
