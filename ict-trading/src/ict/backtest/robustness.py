"""Gate 4: does a result survive being poked?

A backtest gives one number from one parameter set on one ordering of trades.
Both are accidents. This module asks the two questions that separate a result
from a coincidence:

**Parameter sensitivity.** A real edge degrades gently as a parameter moves.
One that collapses the moment a threshold shifts was fitted to the sample: the
search found the one setting where the noise happened to line up. The measure
here is the share of neighbouring settings that stay profitable, and the spread
of expectancy across them.

**Monte Carlo.** Trade order decides the drawdown, and trade order is luck.
Reshuffling the same trades many times gives the distribution of drawdowns the
strategy could have produced, and the worst case matters more than the observed
one, because the observed one is a single draw. Resampling with replacement
also gives a confidence interval on expectancy, which answers the question the
headline number cannot: could this have been zero?

Neither test can make a bad strategy good. Both can show that an apparently
good one was never good, which is the point.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .broker import Trade
from .engine import BacktestResult, run
from .models import ModelConfig
from .report import Metrics, measure
from .strategy import Context


@dataclass
class Variant:
    """One parameter setting and what it produced."""

    settings: dict
    metrics: Metrics

    @property
    def label(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in self.settings.items())


@dataclass
class Sensitivity:
    """Every neighbouring setting, and how much the result moved."""

    baseline: Variant
    variants: list[Variant]

    @property
    def profitable_share(self) -> float:
        """The share of settings with positive expectancy.

        A strategy whose edge exists at one setting and nowhere near it has no
        edge. Something above roughly 0.7 is what a robust result looks like.
        """
        scored = [v for v in self.variants if v.metrics.trades]
        if not scored:
            return float("nan")
        return sum(1 for v in scored if v.metrics.expectancy_r > 0) / len(scored)

    @property
    def expectancy_spread(self) -> float:
        """Best minus worst expectancy across the neighbourhood."""
        scored = [v.metrics.expectancy_r for v in self.variants if v.metrics.trades]
        return max(scored) - min(scored) if scored else float("nan")

    @property
    def worst(self) -> Variant | None:
        scored = [v for v in self.variants if v.metrics.trades]
        return min(scored, key=lambda v: v.metrics.expectancy_r) if scored else None

    def passes(self, minimum_share: float = 0.7) -> bool:
        share = self.profitable_share
        return bool(share == share and share >= minimum_share)


@dataclass
class MonteCarlo:
    """What the same trades could have produced in a different order."""

    samples: int
    observed_drawdown: float
    drawdowns: np.ndarray
    expectancies: np.ndarray
    ruin_threshold: float
    trades: int = 0

    @property
    def median_drawdown(self) -> float:
        return float(np.median(self.drawdowns))

    @property
    def worst_drawdown(self) -> float:
        return float(self.drawdowns.max())

    def drawdown_percentile(self, percentile: float) -> float:
        return float(np.percentile(self.drawdowns, percentile))

    @property
    def risk_of_ruin(self) -> float:
        """Share of orderings whose drawdown passed the ruin threshold.

        Not literal ruin, but the drawdown past which most people stop trading
        the system, which ends it just as surely.
        """
        return float((self.drawdowns >= self.ruin_threshold).mean())

    def expectancy_interval(self, confidence: float = 0.95) -> tuple[float, float]:
        """A percentile interval for expectancy, from resampling with replacement."""
        tail = (1.0 - confidence) / 2.0 * 100.0
        return (
            float(np.percentile(self.expectancies, tail)),
            float(np.percentile(self.expectancies, 100.0 - tail)),
        )

    @property
    def positive_share(self) -> float:
        """How often a resample was profitable at all."""
        return float((self.expectancies > 0).mean())

    def passes(self, confidence: float = 0.95) -> bool:
        """The lower bound of the expectancy interval must clear zero."""
        low, _ = self.expectancy_interval(confidence)
        return low > 0


def _equity_drawdown(nets: np.ndarray, starting_equity: float) -> float:
    """Peak to trough drawdown of an equity curve, as a fraction."""
    equity = starting_equity + np.cumsum(nets)
    peaks = np.maximum.accumulate(np.concatenate([[starting_equity], equity]))
    troughs = np.concatenate([[starting_equity], equity])
    return float(np.max((peaks - troughs) / peaks))


def monte_carlo(
    trades: list[Trade],
    samples: int = 2000,
    starting_equity: float = 10_000.0,
    ruin_threshold: float = 0.30,
    seed: int = 7,
) -> MonteCarlo:
    """Reshuffle and resample the trades to get the distributions.

    Drawdown comes from reshuffling, because it depends on order and the set of
    trades is what the strategy actually produced. Expectancy comes from
    resampling with replacement, because the question there is what a different
    sample of the same process would have given.
    """
    nets = np.array([t.net for t in trades], dtype="float64")
    rs = np.array([t.r_multiple for t in trades], dtype="float64")
    rs = rs[~np.isnan(rs)]

    if len(nets) == 0:
        empty = np.array([float("nan")])
        return MonteCarlo(0, float("nan"), empty, empty, ruin_threshold, 0)

    rng = np.random.default_rng(seed)
    observed = _equity_drawdown(nets, starting_equity)

    drawdowns = np.empty(samples)
    for index in range(samples):
        drawdowns[index] = _equity_drawdown(rng.permutation(nets), starting_equity)

    if len(rs):
        draws = rng.choice(rs, size=(samples, len(rs)), replace=True)
        expectancies = draws.mean(axis=1)
    else:
        expectancies = np.array([float("nan")])

    return MonteCarlo(
        samples=samples,
        observed_drawdown=observed,
        drawdowns=drawdowns,
        expectancies=expectancies,
        ruin_threshold=ruin_threshold,
        trades=len(nets),
    )


def neighbourhood(baseline: ModelConfig, **steps: list[float]) -> list[dict]:
    """Settings one step either side of the baseline, one field at a time.

    Moving one field at a time rather than crossing everything keeps this
    honest. A full grid is a parameter search wearing a robustness test's
    clothes, and the answer wanted here is "does this setting matter", not
    "which combination wins".
    """
    variants: list[dict] = []
    for field_name, offsets in steps.items():
        current = getattr(baseline, field_name)
        for offset in offsets:
            value = current + offset
            if value <= 0 or value == current:
                continue
            variants.append({field_name: round(value, 6)})
    return variants


def sensitivity(
    candles: pd.DataFrame,
    model: str,
    baseline: ModelConfig | None = None,
    steps: dict[str, list[float]] | None = None,
    context: Context | None = None,
    **run_kwargs,
) -> Sensitivity:
    """Run the baseline and its neighbours, and report how far results moved."""
    baseline = baseline or ModelConfig()
    steps = steps or {
        "minimum_r": [-0.5, -0.25, 0.25, 0.5],
        "stop_buffer": [-0.05, 0.05, 0.15],
    }

    from .strategy import build_context

    context = context or build_context(candles)

    base_result = run(
        candles, strategy=model, strategy_config=baseline, context=context, **run_kwargs
    )
    variants = []
    for settings in neighbourhood(baseline, **steps):
        # replace, not a fresh ModelConfig: several models carry their own
        # config subclass with extra fields, and rebuilding the base type
        # would drop them.
        config = replace(baseline, **settings)
        result = run(
            candles, strategy=model, strategy_config=config, context=context, **run_kwargs
        )
        variants.append(Variant(settings=settings, metrics=measure(result)))

    return Sensitivity(
        baseline=Variant(settings={}, metrics=measure(base_result)), variants=variants
    )


def report(sense: Sensitivity, carlo: MonteCarlo, model: str) -> str:
    """Both tests, side by side, with what would count as passing."""
    lines = [
        f"Robustness: {model}",
        "=" * 70,
        "",
        "Parameter sensitivity",
        "-" * 70,
        f"{'setting':<28}{'trades':>8}{'PF':>8}{'exp R':>9}{'maxDD':>9}",
    ]
    rows = [sense.baseline] + sense.variants
    for variant in rows:
        label = variant.label or "baseline"
        m = variant.metrics
        lines.append(
            f"{label:<28}{m.trades:>8}{m.profit_factor:>8.2f}"
            f"{m.expectancy_r:>9.3f}{m.max_drawdown:>9.1%}"
        )

    share = sense.profitable_share
    lines += [
        "",
        f"profitable neighbours   {share:.0%}" if share == share else
        "profitable neighbours   no neighbour traded",
        f"expectancy spread       {sense.expectancy_spread:.3f}R",
    ]
    if sense.worst is not None:
        lines.append(f"worst setting           {sense.worst.label}")
    lines.append(
        "A real edge degrades gently. One that only exists at the baseline was"
    )
    lines.append("fitted to the sample.")

    lines += ["", "Monte Carlo", "-" * 70]
    if carlo.trades == 0:
        lines.append("no trades to reshuffle")
        return "\n".join(lines)

    low, high = carlo.expectancy_interval()
    lines += [
        f"{carlo.samples:,} reshuffles of {carlo.trades} trades",
        "",
        f"drawdown observed       {carlo.observed_drawdown:.1%}",
        f"drawdown median         {carlo.median_drawdown:.1%}",
        f"drawdown 95th           {carlo.drawdown_percentile(95):.1%}",
        f"drawdown worst          {carlo.worst_drawdown:.1%}",
        f"risk of ruin            {carlo.risk_of_ruin:.1%} "
        f"(past {carlo.ruin_threshold:.0%})",
        "",
        f"expectancy 95% interval {low:+.3f}R to {high:+.3f}R",
        f"resamples profitable    {carlo.positive_share:.0%}",
        "",
        "The observed drawdown is one draw. Size positions off the 95th, not it.",
    ]
    if carlo.passes():
        lines.append("The expectancy interval clears zero.")
    elif high < 0:
        lines.append(
            "The expectancy interval sits entirely below zero. This is not an "
            "unproven edge, it is a losing one."
        )
    else:
        lines.append(
            "The expectancy interval spans zero, so the edge is not established: "
            "the same trades could have come from a strategy with none."
        )
    return "\n".join(lines)
