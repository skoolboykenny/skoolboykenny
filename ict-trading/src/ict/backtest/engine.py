"""The bar by bar backtest loop.

Event driven and pessimistic. It walks one minute candles in order, and at each
one the strategy may only see what had closed by then. Detectors are run once
over the whole series for speed, then filtered by
:func:`~ict.timeframes.lookahead.knowable_at`, which is equivalent to
re-running them on a truncated series and vastly cheaper.

The loop skips straight over candles outside the Silver Bullet windows when
nothing is live, because three hours of a twenty four hour day are tradeable
and walking the other twenty one is wasted work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from ..analysis import analyse
from ..config import Config, MARKET_TZ
from ..timeframes.resample import resample
from ..timeframes.sessions import market_date
from .broker import Broker, Order, Trade
from .costs import CostModel
from .risk import RiskConfig, RiskManager
from .models import MODELS, BaseModel, ModelConfig, SilverBulletModel
from .strategy import Context, build_context


@dataclass
class BacktestResult:
    """Everything a run produced, ready to report on."""

    trades: list[Trade]
    equity_curve: pd.Series
    starting_equity: float
    final_equity: float
    candles: int
    days: int
    blocked: dict[str, int] = field(default_factory=dict)
    pauses: int = 0
    parameters: dict = field(default_factory=dict)

    def to_frame(self) -> pd.DataFrame:
        """The trades as a frame, for the journal and for inspection."""
        if not self.trades:
            return pd.DataFrame(
                columns=[
                    "opened_at",
                    "closed_at",
                    "direction",
                    "entry",
                    "exit",
                    "stop",
                    "target",
                    "size",
                    "outcome",
                    "gross",
                    "costs",
                    "net",
                    "r_multiple",
                    "reason",
                ]
            )
        return pd.DataFrame(
            [
                {
                    "opened_at": t.opened_at,
                    "closed_at": t.closed_at,
                    "direction": t.direction,
                    "entry": t.entry,
                    "exit": t.exit,
                    "stop": t.stop,
                    "target": t.target,
                    "size": t.size,
                    "outcome": t.outcome,
                    "gross": t.gross,
                    "costs": t.costs,
                    "net": t.net,
                    "r_multiple": t.r_multiple,
                    "reason": t.reason,
                }
                for t in self.trades
            ]
        )


def run(
    candles: pd.DataFrame,
    strategy: BaseModel | str | Callable[[Context], BaseModel] | None = None,
    costs: CostModel | None = None,
    risk: RiskConfig | None = None,
    strategy_config: ModelConfig | None = None,
    detector_config: Config | None = None,
    starting_equity: float = 10_000.0,
    context: Context | None = None,
) -> BacktestResult:
    """Run one model over ``candles`` and return what happened.

    ``strategy`` is a model instance, a name from
    :data:`~ict.backtest.models.MODELS`, or None for the Silver Bullet.

    ``context`` lets a caller analyse once and run many models or many folds
    over the same candles. Analysing is most of the cost, so a walk forward
    that rebuilt it per fold would spend all its time in the detectors.
    """
    costs = costs or CostModel()
    risk = risk or RiskConfig()

    if candles.empty:
        return BacktestResult(
            trades=[],
            equity_curve=pd.Series(dtype="float64"),
            starting_equity=starting_equity,
            final_equity=starting_equity,
            candles=0,
            days=0,
        )

    if context is None:
        context = build_context(candles, detector_config=detector_config)

    if isinstance(strategy, BaseModel):
        model = strategy
    elif callable(strategy) and not isinstance(strategy, str):
        # A factory, so a caller can configure a model without having built
        # the context itself.
        model = strategy(context)
    else:
        chosen = MODELS[strategy] if strategy else SilverBulletModel
        model = chosen(context, strategy_config)

    broker = Broker(costs=costs)
    manager = RiskManager(config=risk, starting_equity=starting_equity)

    median_spread = (
        float(candles["spread"].median()) if "spread" in candles.columns else 0.0
    )

    tradeable = model.tradeable_mask(candles.index)
    days = market_date(candles.index).to_numpy()
    weeks = candles.index.tz_convert(MARKET_TZ).isocalendar().week.to_numpy()

    equity_stamps: list[pd.Timestamp] = []
    equity_values: list[float] = []
    current_day = None
    current_week = None
    pauses = 0
    settled = 0

    for position, (stamp, candle) in enumerate(candles.iterrows()):
        day = days[position]
        if day != current_day:
            manager.start_day(day)
            current_day = day

        week = weeks[position]
        if week != current_week:
            if manager.paused:
                manager.resume()
                pauses += 1
            current_week = week

        # Resolve anything live, on every candle, in or out of a window.
        if not broker.is_idle:
            before = len(broker.trades)
            broker.on_candle(stamp, candle)
            if len(broker.trades) > before:
                trade = broker.trades[-1]
                manager.record(trade.net)
                equity_stamps.append(stamp)
                equity_values.append(manager.equity)
                settled += 1

        if not tradeable[position]:
            continue
        if not broker.is_idle:
            continue
        if not manager.may_trade():
            continue

        spread = costs.spread_at(candle)
        if not costs.is_tradeable(spread, median_spread):
            manager.blocked["spread too wide"] = (
                manager.blocked.get("spread too wide", 0) + 1
            )
            continue

        setup = model.find_setup(stamp, candle)
        if setup is None:
            continue

        # A stop closer to entry than the cost of getting in is not a trade:
        # the fill lands at or past it, so the loss is booked before price
        # moves. Cheap to spot here and impossible for a model to spot, since
        # the model never sees the spread.
        if setup.risk <= spread + costs.slippage:
            manager.blocked["stop inside cost"] = (
                manager.blocked.get("stop inside cost", 0) + 1
            )
            continue

        size = manager.size_for(setup.risk)
        if size <= 0:
            continue
        broker.place(
            Order(
                placed_at=stamp,
                direction=setup.direction,
                limit=setup.limit,
                stop=setup.stop,
                target=setup.target,
                size=size,
                expires_at=setup.expires_at or (stamp + model.order_life()),
                reason=setup.reason,
            )
        )

    # Nothing is carried past the end of the data.
    if not broker.is_idle:
        last_stamp = candles.index[-1]
        broker.close_now(last_stamp, candles.iloc[-1], "backtest_end")
        if len(broker.trades) > settled:
            trade = broker.trades[-1]
            manager.record(trade.net)
            equity_stamps.append(last_stamp)
            equity_values.append(manager.equity)

    curve = pd.Series(equity_values, index=pd.DatetimeIndex(equity_stamps))
    return BacktestResult(
        trades=list(broker.trades),
        equity_curve=curve,
        starting_equity=starting_equity,
        final_equity=manager.equity,
        candles=len(candles),
        days=int(pd.Series(days).nunique()),
        blocked=dict(manager.blocked),
        pauses=pauses,
        parameters={
            "model": model.name,
            "risk_per_trade": risk.risk_per_trade,
            "max_trades_per_day": risk.max_trades_per_day,
            "minimum_r": model.config.minimum_r,
            "stop_buffer": model.config.stop_buffer,
            "order_life_minutes": model.config.order_life_minutes,
            "windows": list(model.config.windows),
            "fallback_spread": costs.fallback_spread,
            "slippage": costs.slippage,
            "commission": costs.commission,
        },
    )
