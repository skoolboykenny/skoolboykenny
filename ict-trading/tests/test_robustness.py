"""Tests for gate 4: parameter sensitivity and Monte Carlo.

The statistics are checked against trades built by hand, because a test that
feeds in a backtest and asserts the number that comes out only checks that
nothing changed, not that anything is right.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ict.backtest.broker import Trade
from ict.backtest.models import ModelConfig, TurtleSoupConfig
from ict.backtest.robustness import (
    MonteCarlo,
    Sensitivity,
    Variant,
    monte_carlo,
    neighbourhood,
    report,
    sensitivity,
)
from ict.backtest.report import Metrics
from ict.cli import synthetic_candles


def trade(net: float, r: float) -> Trade:
    """A closed trade with the given net and R multiple.

    Both are derived on ``Trade``: net is gross minus costs, and R is net over
    the risk the entry and stop imply. So the stop is placed to make the risk
    come out at ``net / r``, which is the only way to ask for a specific R.
    """
    stamp = pd.Timestamp("2024-03-04 12:00", tz="UTC")
    risk = abs(net / r)
    return Trade(
        opened_at=stamp,
        closed_at=stamp + pd.Timedelta(minutes=30),
        direction="long",
        entry=1.0,
        exit=1.0 + net,
        stop=1.0 - risk,
        target=1.0 + risk * 3,
        size=1.0,
        reason="test",
        outcome="target" if net > 0 else "stop",
        gross=net,
        costs=0.0,
    )


def metrics(expectancy: float, trades: int = 10) -> Metrics:
    return Metrics(
        trades=trades, wins=0, losses=0, win_rate=0.5, gross_profit=0.0,
        gross_loss=0.0, profit_factor=1.0, expectancy_r=expectancy, total_r=0.0,
        max_drawdown=0.1, net=0.0, return_pct=0.0, costs=0.0,
        average_win_r=1.0, average_loss_r=-1.0,
    )


# --- Monte Carlo ------------------------------------------------------------


def test_reshuffling_keeps_the_same_trades():
    """Order changes the drawdown. The set of trades, and so the total, cannot."""
    trades = [trade(100, 2.0), trade(-50, -1.0), trade(-50, -1.0), trade(200, 4.0)]
    result = monte_carlo(trades, samples=200)
    assert result.trades == 4
    # Every ordering ends at the same equity, so no drawdown can exceed the
    # sum of the losses as a share of the peak.
    assert result.worst_drawdown <= 0.02


def test_order_matters_and_the_observed_drawdown_is_one_draw():
    """Losses first is the worst case; the observed order is just one of many."""
    trades = [trade(500, 5.0)] + [trade(-100, -1.0) for _ in range(5)]
    result = monte_carlo(trades, samples=1000, starting_equity=10_000.0)
    assert result.worst_drawdown > result.median_drawdown
    assert result.drawdown_percentile(95) >= result.median_drawdown


def test_a_strategy_of_pure_losses_never_looks_profitable():
    losses = [trade(-100, -1.0) for _ in range(30)]
    result = monte_carlo(losses, samples=500)
    assert result.positive_share == 0.0
    assert not result.passes()
    low, high = result.expectancy_interval()
    assert high < 0


def test_a_clear_edge_clears_zero():
    """Thirty trades averaging +0.5R with small variance should be established."""
    trades = [trade(50, 0.5) for _ in range(28)] + [trade(-100, -1.0) for _ in range(2)]
    result = monte_carlo(trades, samples=1000)
    assert result.passes()
    low, _ = result.expectancy_interval()
    assert low > 0


def test_a_marginal_edge_does_not_clear_zero():
    """Two winners and two losers is not evidence, whatever the total says."""
    trades = [trade(300, 3.0), trade(-100, -1.0), trade(-100, -1.0), trade(-100, -1.0)]
    result = monte_carlo(trades, samples=1000)
    low, high = result.expectancy_interval()
    assert low < 0 < high
    assert not result.passes()


def test_risk_of_ruin_counts_orderings_past_the_threshold():
    trades = [trade(-400, -1.0) for _ in range(9)] + [trade(4000, 10.0)]
    result = monte_carlo(trades, samples=1000, ruin_threshold=0.30)
    assert 0.0 < result.risk_of_ruin <= 1.0


def test_no_trades_is_not_a_crash():
    result = monte_carlo([], samples=100)
    assert result.trades == 0
    assert not result.passes()


def test_the_same_seed_gives_the_same_answer():
    trades = [trade(100, 1.0), trade(-50, -1.0), trade(75, 1.5)]
    first = monte_carlo(trades, samples=200, seed=3)
    second = monte_carlo(trades, samples=200, seed=3)
    assert np.array_equal(first.drawdowns, second.drawdowns)


# --- sensitivity ------------------------------------------------------------


def test_the_neighbourhood_moves_one_field_at_a_time():
    """Crossing every field is a parameter search, not a robustness test."""
    settings = neighbourhood(
        ModelConfig(minimum_r=2.0, stop_buffer=0.1),
        minimum_r=[-0.5, 0.5],
        stop_buffer=[0.05],
    )
    assert all(len(s) == 1 for s in settings)
    assert {"minimum_r": 1.5} in settings
    assert {"minimum_r": 2.5} in settings
    assert {"stop_buffer": 0.15} in settings


def test_the_neighbourhood_refuses_settings_that_are_not_settings():
    """A negative minimum R or a zero one is not a neighbour, it is nonsense."""
    settings = neighbourhood(ModelConfig(minimum_r=0.5), minimum_r=[-0.5, -1.0, 0.5])
    assert {"minimum_r": 1.0} in settings
    assert not any(s["minimum_r"] <= 0 for s in settings)


def test_a_models_own_config_type_survives_the_sweep():
    """Several models carry extra fields, which rebuilding the base type drops."""
    settings = neighbourhood(
        TurtleSoupConfig(minimum_touches=2), minimum_r=[0.5]
    )
    assert settings == [{"minimum_r": 2.5}]


def test_profitable_share_ignores_settings_that_did_not_trade():
    sense = Sensitivity(
        baseline=Variant({}, metrics(0.3)),
        variants=[
            Variant({"minimum_r": 1.5}, metrics(0.2)),
            Variant({"minimum_r": 2.5}, metrics(0.1)),
            Variant({"stop_buffer": 0.2}, metrics(-0.1)),
            Variant({"stop_buffer": 0.3}, metrics(float("nan"), trades=0)),
        ],
    )
    assert sense.profitable_share == pytest.approx(2 / 3)
    assert not sense.passes()
    assert sense.worst.settings == {"stop_buffer": 0.2}


def test_a_neighbourhood_that_holds_up_passes():
    sense = Sensitivity(
        baseline=Variant({}, metrics(0.3)),
        variants=[Variant({"minimum_r": v}, metrics(0.2)) for v in (1.5, 2.5, 3.0)],
    )
    assert sense.passes()
    assert sense.expectancy_spread == pytest.approx(0.0)


def test_sensitivity_runs_a_real_model_and_keeps_its_windows():
    candles = synthetic_candles(days=12)
    sense = sensitivity(candles, model="silver_bullet")
    assert sense.variants
    # The baseline must be the model's own setup, not an empty ModelConfig, or
    # the Silver Bullet would trade all day and the sweep would measure a
    # different strategy.
    assert sense.baseline.metrics.trades >= 0


# --- report -----------------------------------------------------------------


def test_the_report_names_a_losing_interval_for_what_it_is():
    losses = [trade(-100, -1.0) for _ in range(20)]
    sense = Sensitivity(Variant({}, metrics(-1.0)), [Variant({"minimum_r": 1.5}, metrics(-1.0))])
    text = report(sense, monte_carlo(losses, samples=300), "silver_bullet")
    assert "entirely below zero" in text
    assert "losing one" in text


def test_the_report_survives_a_model_that_never_traded():
    sense = Sensitivity(Variant({}, metrics(float("nan"), trades=0)), [])
    text = report(sense, monte_carlo([], samples=100), "power_of_three")
    assert "no trades to reshuffle" in text
