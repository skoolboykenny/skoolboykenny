"""The live loop: prices in, orders out, with the brakes wired in first.

The engine that backtests and the loop that trades have to be the same logic,
or paper trading measures something the backtest never tested. So this module
does as little as possible. It turns a price stream into closed 1 minute
candles, hands them to the same detectors and the same models, sizes through
the same :class:`~ict.backtest.risk.RiskManager`, and sends what comes out.

What it adds is the part a backtest never needs:

**Only closed candles count.** The forming candle is excluded, always. This is
the same lookahead rule the whole project is built on, and live is where it is
easiest to break, because the forming candle is right there.

**A halt that cannot be argued with.** Connection loss, a stale stream, a
drawdown past the worst the backtest saw, or a run of losses, and the loop
cancels everything, closes everything, and stops. It does not retry into a
market it has lost track of.

**Reconciliation before every decision.** The account is the truth, not the
loop's memory. A position opened by a fill the loop never saw is still a
position, and the loop asks the broker rather than assuming.

Nothing here runs without a broker. See ``docs/live.md`` before using it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace

import pandas as pd

from ..analysis import analyse
from ..backtest.models import MODELS, BaseModel, ModelConfig
from ..backtest.risk import RiskConfig, RiskManager
from ..backtest.strategy import Context, Setup
from ..config import Config, MARKET_TZ
from ..timeframes.resample import resample
from ..timeframes.sessions import market_date
from .broker import LiveBroker

log = logging.getLogger("ict.live")

#: How long without a price or heartbeat before the stream is called dead.
STALE_AFTER = pd.Timedelta(seconds=30)


@dataclass
class Guards:
    """The conditions that stop trading, and stop it for good."""

    #: Halt if equity falls this far below its peak. Set from the worst
    #: drawdown the backtest saw, not from what feels tolerable.
    max_drawdown: float = 0.15
    #: Halt after this many losses in a row.
    max_consecutive_losses: int = 8
    #: Halt if the stream goes quiet for this long.
    stale_after: pd.Timedelta = STALE_AFTER
    #: Refuse to trade when the spread is this multiple of its own median.
    max_spread_multiple: float = 2.0


@dataclass
class Halt:
    """Why the loop stopped. A halt is final and needs a person."""

    reason: str
    at: pd.Timestamp
    detail: str = ""

    def __str__(self) -> str:
        return f"HALT {self.reason} at {self.at:%Y-%m-%d %H:%M:%S}: {self.detail}"


@dataclass
class CandleBuilder:
    """Turns a tick stream into closed 1 minute candles.

    Yields a candle only once the minute after it has begun, so what comes out
    is always complete. The forming minute is held back, which is the whole
    point: a high that has not finished forming is not a high.
    """

    _minute: pd.Timestamp | None = None
    _values: list[float] = field(default_factory=list)
    _spreads: list[float] = field(default_factory=list)

    def add(self, at: pd.Timestamp, bid: float, ask: float) -> pd.Series | None:
        """Add a tick, returning the previous candle if this tick closed it."""
        minute = pd.Timestamp(at).tz_convert("UTC").floor("min")
        mid = (bid + ask) / 2.0
        closed = None

        if self._minute is None:
            self._minute = minute
        elif minute > self._minute:
            closed = self._close()
            self._minute = minute

        self._values.append(mid)
        self._spreads.append(ask - bid)
        return closed

    def _close(self) -> pd.Series | None:
        if not self._values:
            return None
        candle = pd.Series(
            {
                "open": self._values[0],
                "high": max(self._values),
                "low": min(self._values),
                "close": self._values[-1],
                "volume": float(len(self._values)),
                "spread": sum(self._spreads) / len(self._spreads),
            },
            name=self._minute,
        )
        self._values = []
        self._spreads = []
        return candle


class LiveRunner:
    """One instrument, one model, one account.

    ``history`` is the candles already on disk. The detectors need context to
    work at all, so the loop starts from real history and appends to it rather
    than waking up blind.
    """

    def __init__(
        self,
        broker: LiveBroker,
        history: pd.DataFrame,
        model: str = "silver_bullet",
        model_config: ModelConfig | None = None,
        overrides: dict | None = None,
        risk: RiskConfig | None = None,
        detector_config: Config | None = None,
        guards: Guards | None = None,
        news_gate=None,
        reviewer=None,
        journal=None,
        dry_run: bool = True,
    ) -> None:
        if history.empty:
            raise ValueError(
                "the runner needs history: detectors cannot see structure in "
                "a series that started this minute"
            )
        self.broker = broker
        self.candles = history.copy()
        self.model_name = model
        self.model_config = model_config
        #: Applied on top of the model's own defaults, so a setting given here
        #: does not silently discard the windows the model trades.
        self.overrides = overrides or {}
        self.detector_config = detector_config
        self.guards = guards or Guards()
        self.news_gate = news_gate
        self.reviewer = reviewer
        self.journal = journal
        self.dry_run = dry_run

        equity = broker.equity() if not dry_run else 10_000.0
        self.risk = RiskManager(config=risk or RiskConfig(), starting_equity=equity)
        self.risk.start_day(market_date(pd.DatetimeIndex([self.candles.index[-1]])).iloc[0])

        self.builder = CandleBuilder()
        self.halted: Halt | None = None
        self.consecutive_losses = 0
        self.last_message: pd.Timestamp | None = None
        self.placed: list = []
        self._context: Context | None = None
        self._analysed_through: pd.Timestamp | None = None

    # --- state -------------------------------------------------------------

    def context(self) -> Context:
        """The detector output, rebuilt when new candles have arrived.

        Re-analysing the whole series on every candle would not keep up, and
        re-analysing only the tail would lose the structure that gives the tail
        its meaning. So it rebuilds when the data has actually changed, on the
        minute boundary, which is once every sixty seconds at most.
        """
        latest = self.candles.index[-1]
        if self._context is None or self._analysed_through != latest:
            entry = analyse(self.candles, config=self.detector_config, with_levels=True)
            hourly = resample(self.candles, "1h")
            draw = analyse(hourly, config=self.detector_config, with_levels=True)
            self._context = Context(entry=entry, draw=draw)
            self._analysed_through = latest
        return self._context

    def model(self) -> BaseModel:
        model = MODELS[self.model_name](self.context(), self.model_config)
        if self.overrides:
            model.config = replace(model.config, **self.overrides)
        return model

    # --- the loop ----------------------------------------------------------

    def halt(self, reason: str, detail: str = "") -> Halt:
        """Stop trading, flatten, and stay stopped."""
        at = pd.Timestamp.now(tz="UTC")
        self.halted = Halt(reason=reason, at=at, detail=detail)
        log.error("%s", self.halted)
        if not self.dry_run:
            try:
                cancelled = self.broker.cancel_all()
                closed = self.broker.close_all()
                log.error("flattened: %d orders cancelled, %d positions closed",
                          cancelled, closed)
            except Exception as error:  # a halt must not raise
                log.exception("could not flatten on halt: %s", error)
        return self.halted

    def check_guards(self, now: pd.Timestamp) -> Halt | None:
        """Everything that should stop the loop, checked before it acts."""
        if self.halted:
            return self.halted

        if self.last_message is not None:
            quiet = now - self.last_message
            if quiet > self.guards.stale_after:
                return self.halt(
                    "stale stream",
                    f"no message for {quiet.total_seconds():.0f}s",
                )

        peak = self.risk.peak_equity
        if peak > 0:
            drawdown = (peak - self.risk.equity) / peak
            if drawdown >= self.guards.max_drawdown:
                return self.halt(
                    "drawdown",
                    f"{drawdown:.1%} from peak, limit {self.guards.max_drawdown:.1%}",
                )

        if self.consecutive_losses >= self.guards.max_consecutive_losses:
            return self.halt(
                "losing run", f"{self.consecutive_losses} losses in a row"
            )
        return None

    def on_message(self, message: dict) -> Setup | None:
        """One message from the stream. Returns a setup if one was placed.

        Heartbeats only refresh the clock. A price builds candles, and a closed
        candle is the only thing that can produce a trade.
        """
        kind = message.get("type")
        now = pd.Timestamp.now(tz="UTC")
        self.last_message = now

        if kind == "HEARTBEAT":
            self.check_guards(now)
            return None
        if kind != "PRICE":
            return None

        bids, asks = message.get("bids") or [], message.get("asks") or []
        if not bids or not asks:
            return None
        if message.get("tradeable") is False:
            return None

        closed = self.builder.add(
            pd.Timestamp(message["time"]),
            float(bids[0]["price"]),
            float(asks[0]["price"]),
        )
        if closed is None:
            return None
        return self.on_candle(closed)

    def on_candle(self, candle: pd.Series) -> Setup | None:
        """A closed 1 minute candle: the only point at which anything happens."""
        stamp = pd.Timestamp(candle.name)
        self.candles.loc[stamp] = candle
        self.candles = self.candles.sort_index()

        day = market_date(pd.DatetimeIndex([stamp])).iloc[0]
        if self.risk.day is None or self.risk.day.day != day:
            self.risk.start_day(day)

        if self.check_guards(stamp):
            return None

        self.reconcile()
        if self.halted:
            return None

        model = self.model()
        if not model.tradeable_at(stamp):
            return None

        # A risk check, so it runs before the model is asked rather than being
        # something the model could forget.
        if self.news_gate is not None:
            blackout = self.news_gate.blocked_at(stamp)
            if blackout is not None:
                log.info("blocked by news: %s", blackout)
                return None

        if not self.risk.may_trade():
            return None
        if not self.dry_run and not self.broker.is_idle:
            return None

        spread = float(candle.get("spread", 0.0))
        median = float(self.candles["spread"].tail(1440).median()) if "spread" in self.candles else 0.0
        if median > 0 and spread > median * self.guards.max_spread_multiple:
            log.info("skipped %s: spread %.6f against median %.6f", stamp, spread, median)
            return None

        setup = model.find_setup(stamp, candle)
        if setup is None:
            return None

        if setup.risk <= spread:
            log.info("skipped %s: stop inside the spread", stamp)
            return None

        size = self.risk.size_for(setup.risk)
        if size <= 0:
            return None

        # The review layer runs last, on a setup that already passed every
        # check code enforces, and may only shrink it or cancel it.
        if self.reviewer is not None:
            verdict = self.ask_reviewer(setup, stamp, model)
            if verdict.blocks:
                log.info("review layer skipped %s: %s", stamp, verdict.reason)
                return None
            if verdict.size_multiple < 1.0:
                log.info("review layer reduced to %.0f%%: %s",
                         verdict.size_multiple * 100, verdict.reason)
            size *= verdict.size_multiple
            if size <= 0:
                return None

        if self.dry_run:
            log.info("DRY RUN would place %s %s @ %.5f stop %.5f target %.5f size %.0f",
                     setup.direction, self.broker.instrument_name, setup.limit,
                     setup.stop, setup.target, size)
            return setup

        expiry = setup.expires_at or (stamp + model.order_life())
        order = self.broker.place(setup, size, expires_at=expiry, client_tag=self.model_name)
        self.placed.append(order)
        log.info("placed %s: %s %.0f units @ %.5f", order.order_id,
                 setup.direction, order.units, setup.limit)
        return setup

    def ask_reviewer(self, setup: Setup, stamp: pd.Timestamp, model: BaseModel):
        """Put one setup to the review layer and record the answer.

        The layer sees structured fields and never a chart. Upcoming events
        come from the same gate the risk check uses, so the reviewer is
        reasoning about the releases that are actually scheduled rather than
        whatever it remembers.
        """
        from ..review import ReviewRequest

        upcoming = []
        if self.news_gate is not None:
            horizon = stamp + pd.Timedelta(minutes=model.config.order_life_minutes + 60)
            upcoming = [
                str(b) for b in self.news_gate.blackouts
                if stamp <= b.start <= horizon
            ][:5]

        request = ReviewRequest(
            instrument=self.broker.instrument_name,
            at=stamp,
            direction=setup.direction,
            entry=setup.limit,
            stop=setup.stop,
            target=setup.target,
            reward_to_risk=setup.reward_to_risk,
            model=model.name,
            reason=setup.reason,
            session=str(stamp.tz_convert(MARKET_TZ).strftime("%H:%M")),
            upcoming_events=upcoming,
            recent_performance={
                "equity": self.risk.equity,
                "peak_equity": self.risk.peak_equity,
                "trades_today": self.risk.day.trades if self.risk.day else 0,
                "consecutive_losses": self.consecutive_losses,
            },
        )
        verdict = self.reviewer.review(request)
        if self.journal is not None:
            self.journal.record(request, verdict)
        return verdict

    def reconcile(self) -> None:
        """Bring the loop's view of the account back to what the account says.

        The broker is the truth. A stop may have filled while the stream was
        quiet, and the loop would otherwise keep sizing off equity that no
        longer exists.
        """
        if self.dry_run:
            return
        try:
            equity = self.broker.equity()
        except Exception as error:
            self.halt("broker unreachable", str(error))
            return

        change = equity - self.risk.equity
        if abs(change) > 1e-9:
            self.risk.record(change)
            if change < 0:
                self.consecutive_losses += 1
            else:
                self.consecutive_losses = 0

    def run(self, instruments: list[str] | None = None) -> Halt | None:
        """Stream prices until something halts the loop.

        Returns the halt, so a supervisor can log it and stay stopped. It never
        restarts itself: a loop that restarts through its own kill switch does
        not have one.
        """
        names = instruments or [self.broker.instrument_name]
        log.info("live runner starting: %s, model %s, dry_run=%s",
                 ", ".join(names), self.model_name, self.dry_run)
        try:
            for message in self.broker.client.stream_prices(names):
                self.on_message(message)
                if self.halted:
                    break
        except KeyboardInterrupt:
            self.halt("stopped by hand", "keyboard interrupt")
        except Exception as error:
            self.halt("stream failed", str(error))
        return self.halted
