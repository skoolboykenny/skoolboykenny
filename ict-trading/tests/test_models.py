"""Tests for the ICT model set and the walk forward.

The models share the detector library and the context, so what is tested here
is the rule each one adds: which window it trades, what it insists on before
entering, and where it puts the stop and target.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ict.backtest import MODELS, run
from ict.backtest.models import (
    JudasSwingModel,
    Mentorship2022Model,
    ModelConfig,
    OTEModel,
    PowerOfThreeModel,
    SilverBulletModel,
    SweepToSweepModel,
    TurtleSoupModel,
)
from ict.backtest.strategy import Setup, build_context
from ict.backtest.walkforward import grid, rank, walk_forward, windows
from ict.cli import synthetic_candles


@pytest.fixture(scope="module")
def context():
    return build_context(synthetic_candles(days=30))


@pytest.fixture(scope="module")
def candles():
    return synthetic_candles(days=30)


# --- the model set ----------------------------------------------------------


def test_every_model_in_the_record_is_registered():
    assert set(MODELS) == {
        "silver_bullet",
        "mentorship_2022",
        "optimal_trade_entry",
        "power_of_three",
        "judas_swing",
        "turtle_soup",
        "sweep_to_sweep",
    }


def test_each_model_runs_and_reports_its_own_name(candles, context):
    for name in MODELS:
        result = run(candles, strategy=name, context=context)
        assert result.parameters["model"] == name
        assert result.candles == len(candles)


def test_models_trade_the_windows_they_claim(context):
    index = pd.date_range(
        "2024-03-04", periods=24 * 60, freq="1min", tz="UTC"
    )

    # The Silver Bullet trades three one hour windows, so it must be tradeable
    # far less often than a model with no window restriction.
    sb = SilverBulletModel(context).tradeable_mask(index)
    anytime = SweepToSweepModel(context).tradeable_mask(index)

    assert anytime.all()
    assert 0 < sb.mean() < 0.25


def test_a_setup_below_the_minimum_r_is_refused(context):
    model = SilverBulletModel(context, ModelConfig(minimum_r=10.0))
    generous = SilverBulletModel(context, ModelConfig(minimum_r=0.5))

    # Same data, same rule, different bar: the strict one must trade less.
    strict = run(synthetic_candles(days=30), strategy=model, context=context)
    loose = run(synthetic_candles(days=30), strategy=generous, context=context)
    assert len(strict.trades) <= len(loose.trades)


def test_setup_arithmetic():
    setup = Setup("long", limit=100.0, stop=99.0, target=103.0, reason="")
    assert setup.risk == pytest.approx(1.0)
    assert setup.reward == pytest.approx(3.0)
    assert setup.reward_to_risk == pytest.approx(3.0)

    short = Setup("short", limit=100.0, stop=101.0, target=94.0, reason="")
    assert short.risk == pytest.approx(1.0)
    assert short.reward_to_risk == pytest.approx(6.0)


def test_every_trade_has_a_stop_on_the_losing_side_of_entry(candles, context):
    """A stop above a long's fill is a loss booked before price moves.

    It happens when the spread is wider than the setup's own risk, so the
    engine refuses those setups outright.
    """
    for name in MODELS:
        frame = run(candles, strategy=name, context=context).to_frame()
        if frame.empty:
            continue
        longs = frame.loc[frame["direction"] == "long"]
        shorts = frame.loc[frame["direction"] == "short"]
        assert (longs["stop"] < longs["entry"]).all(), name
        assert (longs["target"] > longs["entry"]).all(), name
        assert (shorts["stop"] > shorts["entry"]).all(), name
        assert (shorts["target"] < shorts["entry"]).all(), name


def test_power_of_three_needs_the_asian_range(context):
    """Without a finished Asian range there is no manipulation to read."""
    model = PowerOfThreeModel(context)
    # Midnight New York on the first day: Asia has not closed yet.
    early = pd.Timestamp("2024-03-04 00:30", tz="America/New_York").tz_convert("UTC")
    candle = pd.Series({"close": 1.0850, "high": 1.0855, "low": 1.0845})
    assert model.find_setup(early, candle) is None


def test_judas_swing_needs_the_midnight_open(context):
    model = JudasSwingModel(context)
    before_any_day = context.entry.candles.index[0]
    candle = context.entry.candles.iloc[0]
    assert model.find_setup(before_any_day, candle) is None


def test_turtle_soup_wants_an_obvious_level(context):
    """One touch is a swing. Two or more is a level people can see."""
    from ict.backtest.models import TurtleSoupConfig

    picky = TurtleSoupModel(context, TurtleSoupConfig(minimum_touches=99))
    relaxed = TurtleSoupModel(context, TurtleSoupConfig(minimum_touches=1))

    data = synthetic_candles(days=30)
    assert len(run(data, strategy=picky, context=context).trades) <= len(
        run(data, strategy=relaxed, context=context).trades
    )


def test_models_do_not_look_ahead(candles):
    """The property test from the engine, applied to every model.

    Re-running on truncated data must not change trades that already closed.
    """
    cut = candles.index[len(candles) * 2 // 3]
    truncated = candles.loc[candles.index <= cut]

    for name in MODELS:
        full = run(candles, strategy=name).to_frame()
        short = run(truncated, strategy=name).to_frame()
        if full.empty:
            continue
        settled = full.loc[full["closed_at"] < cut].reset_index(drop=True)
        matching = short.loc[short["closed_at"] < cut].reset_index(drop=True)
        assert len(settled) == len(matching), f"{name} changed its finished trades"
        if not settled.empty:
            pd.testing.assert_series_equal(
                settled["opened_at"], matching["opened_at"], check_names=False
            )


# --- walk forward -----------------------------------------------------------


def test_windows_roll_and_do_not_overlap_their_tests(candles):
    folds = windows(candles, train_days=10, test_days=5)
    assert len(folds) > 1
    for earlier, later in zip(folds, folds[1:]):
        assert later.test_start >= earlier.test_end
        assert earlier.train_end == earlier.test_start


def test_a_window_longer_than_the_data_yields_no_folds(candles):
    assert windows(candles, train_days=500, test_days=100) == []


def test_the_grid_is_every_combination():
    combinations = grid(minimum_r=[1.0, 2.0], stop_buffer=[0.1, 0.2, 0.3])
    assert len(combinations) == 6
    assert {"minimum_r": 2.0, "stop_buffer": 0.3} in combinations


def test_walk_forward_reports_only_test_windows(candles, context):
    result = walk_forward(
        candles,
        model="silver_bullet",
        parameters=grid(minimum_r=[1.5, 2.0]),
        train_days=10,
        test_days=5,
        context=context,
    )

    assert result.combinations_tried == 2
    assert len(result.folds) > 0

    # Every pooled trade must come from a test window, never a tuning one.
    pooled = {t.opened_at for t in result.out_of_sample_trades()}
    for trade in pooled:
        assert any(
            fold.window.test_start <= trade < fold.window.test_end
            for fold in result.folds
        )


def test_ranking_sorts_by_out_of_sample_expectancy(candles, context):
    results = [
        walk_forward(
            candles, model=name, train_days=10, test_days=5, context=context
        )
        for name in ("silver_bullet", "sweep_to_sweep")
    ]
    table = rank(results)

    assert list(table.columns)[:4] == ["model", "folds", "empty_folds", "trades"]
    values = [v for v in table["expectancy_r"] if v == v]
    assert values == sorted(values, reverse=True)


def test_empty_folds_are_counted_not_dropped(candles, context):
    """A model that rarely fires must not look like one that always wins."""
    quiet = walk_forward(
        candles,
        model="power_of_three",
        train_days=10,
        test_days=5,
        context=context,
    )
    assert quiet.empty_folds <= len(quiet.folds)
    assert quiet.empty_folds == sum(1 for f in quiet.folds if f.test.trades == 0)
