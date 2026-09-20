"""Turning a run into numbers, and into a verdict.

The pass criteria come from the project record: profit factor above 1.3,
expectancy above 0.2R per trade, maximum drawdown below 15%, and at least 200
out of sample trades. All four, not whichever three look best.

The report also prints how many parameter combinations were tried, because
testing many ICT variants inflates the chance of a lucky result and a headline
profit factor means little without that denominator.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .engine import BacktestResult

MIN_PROFIT_FACTOR = 1.3
MIN_EXPECTANCY_R = 0.2
MAX_DRAWDOWN = 0.15
MIN_TRADES = 200


@dataclass(frozen=True)
class Metrics:
    """The numbers a strategy is judged on."""

    trades: int
    wins: int
    losses: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    expectancy_r: float
    total_r: float
    max_drawdown: float
    net: float
    return_pct: float
    costs: float
    average_win_r: float
    average_loss_r: float

    def gate(self) -> list[tuple[str, bool, str]]:
        """Each pass criterion, whether it is met, and by how much."""
        return [
            (
                "profit factor above 1.3",
                self.profit_factor >= MIN_PROFIT_FACTOR,
                f"{self.profit_factor:.2f}",
            ),
            (
                "expectancy above 0.2R",
                self.expectancy_r >= MIN_EXPECTANCY_R,
                f"{self.expectancy_r:.3f}R",
            ),
            (
                "max drawdown below 15%",
                self.max_drawdown <= MAX_DRAWDOWN,
                f"{self.max_drawdown:.1%}",
            ),
            (
                "at least 200 trades",
                self.trades >= MIN_TRADES,
                f"{self.trades}",
            ),
        ]

    @property
    def passes(self) -> bool:
        return all(ok for _, ok, _ in self.gate())


def measure(result: BacktestResult) -> Metrics:
    """Compute the metrics for a run."""
    frame = result.to_frame()
    if frame.empty:
        return Metrics(
            trades=0,
            wins=0,
            losses=0,
            win_rate=float("nan"),
            gross_profit=0.0,
            gross_loss=0.0,
            profit_factor=float("nan"),
            expectancy_r=float("nan"),
            total_r=0.0,
            max_drawdown=0.0,
            net=0.0,
            return_pct=0.0,
            costs=0.0,
            average_win_r=float("nan"),
            average_loss_r=float("nan"),
        )

    net = frame["net"]
    wins = net > 0
    losses = net < 0

    gross_profit = float(net.loc[wins].sum())
    gross_loss = float(-net.loc[losses].sum())
    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0 else float("inf")
    )

    curve = result.equity_curve
    if curve.empty:
        drawdown = 0.0
    else:
        with_start = pd.concat(
            [pd.Series([result.starting_equity]), curve.reset_index(drop=True)]
        )
        peak = with_start.cummax()
        drawdown = float(((peak - with_start) / peak).max())

    r = frame["r_multiple"]
    return Metrics(
        trades=len(frame),
        wins=int(wins.sum()),
        losses=int(losses.sum()),
        win_rate=float(wins.mean()),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        expectancy_r=float(r.mean()),
        total_r=float(r.sum()),
        max_drawdown=drawdown,
        net=float(net.sum()),
        return_pct=float(net.sum() / result.starting_equity),
        costs=float(frame["costs"].sum()),
        average_win_r=float(r.loc[wins].mean()) if wins.any() else float("nan"),
        average_loss_r=float(r.loc[losses].mean()) if losses.any() else float("nan"),
    )


def report(
    result: BacktestResult,
    metrics: Metrics,
    combinations_tried: int = 1,
    verified: bool = False,
) -> str:
    """The results report, with the gate applied and the caveats kept."""
    lines: list[str] = []
    add = lines.append

    add("Silver Bullet backtest")
    add("=" * 60)
    add(
        f"{result.candles:,} candles over {result.days} days, "
        f"{metrics.trades} trades"
    )
    add("")

    if metrics.trades == 0:
        add("No trades were taken. Either the setup never occurred in this")
        add("data, or a filter is too tight to ever let one through.")
        if result.blocked:
            add("")
            add("Entries blocked by:")
            for reason, count in sorted(
                result.blocked.items(), key=lambda item: -item[1]
            ):
                add(f"  {reason}: {count:,}")
        return "\n".join(lines)

    add("Results")
    add("-" * 60)
    add(f"  net                  {metrics.net:>12,.2f}")
    add(f"  return               {metrics.return_pct:>12.2%}")
    add(f"  costs paid           {metrics.costs:>12,.2f}")
    add(f"  total R              {metrics.total_r:>12.2f}")
    add(f"  expectancy           {metrics.expectancy_r:>12.3f} R per trade")
    add(f"  profit factor        {metrics.profit_factor:>12.2f}")
    add(f"  win rate             {metrics.win_rate:>12.1%}")
    add(f"  wins / losses        {metrics.wins:>6} / {metrics.losses}")
    add(f"  average win          {metrics.average_win_r:>12.2f} R")
    add(f"  average loss         {metrics.average_loss_r:>12.2f} R")
    add(f"  max drawdown         {metrics.max_drawdown:>12.1%}")
    add("")

    frame = result.to_frame()
    add("Exits")
    add("-" * 60)
    for outcome, count in frame["outcome"].value_counts().items():
        add(f"  {outcome:<20}{count:>6}")
    add("")

    if result.blocked:
        add("Entries blocked by")
        add("-" * 60)
        for reason, count in sorted(result.blocked.items(), key=lambda i: -i[1]):
            add(f"  {reason:<20}{count:>6,}")
        add("")
    if result.pauses:
        add(f"The weekly drawdown pause tripped {result.pauses} time(s).")
        add("")

    add("Pass criteria")
    add("-" * 60)
    for name, ok, value in metrics.gate():
        add(f"  {'pass' if ok else 'FAIL':<6}{name:<30}{value:>10}")
    add("")
    add(
        f"  {'PASSES' if metrics.passes else 'DOES NOT PASS'} "
        "the Phase 2 gate"
    )
    add("")

    add("Read this before believing any of it")
    add("-" * 60)
    add(f"  Parameter combinations tried: {combinations_tried}.")
    if combinations_tried > 1:
        add("  Testing many variants inflates the chance of a lucky result.")
    if not verified:
        add("  The detectors have NOT passed the 90% hand labelling gate.")
        add("  These numbers describe what the code did, not what the market")
        add("  does. Until `ict verify` passes, a profitable result here is")
        add("  evidence about the code, not about the strategy.")
    add("  These are in sample results unless the range was held back.")
    add("  Walk forward and paper trading gates come before any live money.")

    return "\n".join(lines)
