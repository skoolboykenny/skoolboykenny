"""Walk forward: tune on one window, test on the next, roll on.

From the project record: tune on 12 months, test on the next 3, roll forward,
and **report only out of sample results**. That last clause is the whole point.
An in sample result is a statement about how well a parameter search fitted the
data it searched; only the test windows say anything about the future.

Two things this deliberately does not hide.

**The parameter count.** Every combination tried is counted and reported,
because trying many ICT variants inflates the chance of one looking good by
luck, and a profit factor quoted without its denominator is not a result.

**Folds that produced nothing.** A window where the model never traded is
reported as such rather than dropped, since dropping it would quietly turn a
model that rarely fires into one that fires reliably and wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

import pandas as pd

from ..config import Config
from .costs import CostModel
from .engine import BacktestResult, run
from .models import MODELS, BaseModel, ModelConfig
from .report import Metrics, measure
from .risk import RiskConfig
from .strategy import Context, build_context


@dataclass(frozen=True)
class Window:
    """One tune and test pair."""

    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp

    def label(self) -> str:
        return f"{self.test_start:%Y-%m-%d} to {self.test_end:%Y-%m-%d}"


@dataclass
class FoldResult:
    """What one fold produced, in sample and out."""

    window: Window
    chosen: dict
    train: Metrics
    test: Metrics
    test_result: BacktestResult


@dataclass
class WalkForward:
    """Every fold for one model, and the out of sample total."""

    model: str
    folds: list[FoldResult]
    combinations_tried: int

    def out_of_sample_trades(self) -> list:
        """Every trade from a test window, and none from a tuning one."""
        return [t for fold in self.folds for t in fold.test_result.trades]

    @property
    def out_of_sample(self) -> Metrics:
        """The test windows pooled, which is the only number worth quoting."""
        trades = self.out_of_sample_trades()
        equity, stamps, values = 10_000.0, [], []
        for trade in sorted(trades, key=lambda t: t.closed_at):
            equity += trade.net
            stamps.append(trade.closed_at)
            values.append(equity)

        pooled = BacktestResult(
            trades=trades,
            equity_curve=pd.Series(values, index=pd.DatetimeIndex(stamps)),
            starting_equity=10_000.0,
            final_equity=equity,
            candles=sum(f.test_result.candles for f in self.folds),
            days=sum(f.test_result.days for f in self.folds),
        )
        return measure(pooled)

    @property
    def empty_folds(self) -> int:
        return sum(1 for fold in self.folds if fold.test.trades == 0)

    def degradation(self) -> float:
        """How much worse out of sample is than in sample, in expectancy.

        A large gap is the signature of a parameter search fitting noise. A
        model that holds up is one where this is small.
        """
        train = [f.train.expectancy_r for f in self.folds if f.train.trades]
        test = [f.test.expectancy_r for f in self.folds if f.test.trades]
        if not train or not test:
            return float("nan")
        return sum(train) / len(train) - sum(test) / len(test)


def windows(
    candles: pd.DataFrame, train_days: int, test_days: int, step_days: int | None = None
) -> list[Window]:
    """Rolling tune and test windows across the data.

    The record asks for 12 months of tuning and 3 of testing. Anything shorter
    is a smaller version of the same shape, and the caller is told how many
    folds it got so a thin result is visible rather than implied.
    """
    if candles.empty:
        return []
    step = step_days or test_days
    start = candles.index[0]
    end = candles.index[-1]

    out: list[Window] = []
    train_start = start
    while True:
        train_end = train_start + pd.Timedelta(days=train_days)
        test_end = train_end + pd.Timedelta(days=test_days)
        if test_end > end:
            break
        out.append(Window(train_start, train_end, train_end, test_end))
        train_start = train_start + pd.Timedelta(days=step)
    return out


def grid(**options) -> list[dict]:
    """Every combination of the options given, as a list of kwargs."""
    if not options:
        return [{}]
    keys = list(options)
    return [dict(zip(keys, values)) for values in product(*(options[k] for k in keys))]


def walk_forward(
    candles: pd.DataFrame,
    model: str,
    parameters: list[dict] | None = None,
    train_days: int = 120,
    test_days: int = 30,
    costs: CostModel | None = None,
    risk: RiskConfig | None = None,
    detector_config: Config | None = None,
    context: Context | None = None,
) -> WalkForward:
    """Tune and test one model across rolling windows.

    The context is built once and shared by every fold and every parameter
    combination. Detectors are deterministic over the series and every read is
    filtered to what was knowable at the time, so slicing a shared analysis is
    equivalent to re-analysing each slice, and vastly cheaper.
    """
    parameters = parameters or [{}]
    costs = costs or CostModel()
    risk = risk or RiskConfig()
    if context is None:
        context = build_context(candles, detector_config=detector_config)

    def build(settings: dict) -> BaseModel:
        from dataclasses import replace

        built = MODELS[model](context)
        if settings:
            built.config = replace(built.config, **settings)
        return built

    folds: list[FoldResult] = []
    for window in windows(candles, train_days, test_days):
        train = candles.loc[
            (candles.index >= window.train_start) & (candles.index < window.train_end)
        ]
        test = candles.loc[
            (candles.index >= window.test_start) & (candles.index < window.test_end)
        ]
        if train.empty or test.empty:
            continue

        best, best_metrics, best_settings = None, None, {}
        for settings in parameters:
            result = run(
                train, strategy=build(settings), costs=costs, risk=risk,
                context=context,
            )
            metrics = measure(result)
            # Expectancy in R is the ranking number, since it is comparable
            # across models and position sizes in a way currency is not.
            score = metrics.expectancy_r if metrics.trades else float("-inf")
            if best is None or score > best:
                best, best_metrics, best_settings = score, metrics, settings

        tested = run(
            test, strategy=build(best_settings), costs=costs, risk=risk,
            context=context,
        )
        folds.append(
            FoldResult(
                window=window,
                chosen=best_settings,
                train=best_metrics,
                test=measure(tested),
                test_result=tested,
            )
        )

    return WalkForward(
        model=model, folds=folds, combinations_tried=len(parameters)
    )


def rank(results: list[WalkForward]) -> pd.DataFrame:
    """Rank models by out of sample expectancy.

    Sorted by expectancy per trade in R rather than by profit or profit
    factor: R is comparable across models that trade at different rates and
    sizes, and profit factor flatters a model with three lucky trades.
    """
    rows = []
    for item in results:
        out = item.out_of_sample
        rows.append(
            {
                "model": item.model,
                "folds": len(item.folds),
                "empty_folds": item.empty_folds,
                "trades": out.trades,
                "win_rate": out.win_rate,
                "profit_factor": out.profit_factor,
                "expectancy_r": out.expectancy_r,
                "total_r": out.total_r,
                "max_drawdown": out.max_drawdown,
                "degradation_r": item.degradation(),
                "combinations": item.combinations_tried,
                "passes": out.passes,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.sort_values("expectancy_r", ascending=False).reset_index(drop=True)


def report(table: pd.DataFrame, train_days: int, test_days: int) -> str:
    """The ranking, with what it is worth stated next to it."""
    if table.empty:
        return "no walk forward results"

    lines = [
        "Walk forward ranking, out of sample only",
        "=" * 78,
        f"tune {train_days} days, test {test_days} days, rolling",
        "",
        f"{'model':<20}{'trades':>7}{'win%':>7}{'PF':>7}{'exp R':>8}"
        f"{'total R':>9}{'maxDD':>8}{'drift':>8}{'folds':>7}",
        "-" * 78,
    ]
    for _, row in table.iterrows():
        empty = f" ({row['empty_folds']} empty)" if row["empty_folds"] else ""
        lines.append(
            f"{row['model']:<20}{row['trades']:>7}{row['win_rate']:>7.1%}"
            f"{row['profit_factor']:>7.2f}{row['expectancy_r']:>8.3f}"
            f"{row['total_r']:>9.2f}{row['max_drawdown']:>8.1%}"
            f"{row['degradation_r']:>8.3f}{str(int(row['folds'])) + empty:>7}"
        )

    lines += [
        "",
        "drift is in sample expectancy minus out of sample expectancy.",
        "A large positive drift means the tuning fitted noise.",
        "",
        f"Parameter combinations per model: {int(table['combinations'].max())}.",
        "Testing many variants inflates the chance of a lucky winner, so read",
        "the ranking as an ordering to investigate rather than a result.",
        "",
        "No model here has passed the 90% detector gate, and none has run on",
        "real market data. These orderings describe the code, not the market.",
    ]
    return "\n".join(lines)
