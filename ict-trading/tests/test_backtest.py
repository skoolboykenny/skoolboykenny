"""Tests for the backtest engine.

The arithmetic tests use hand built candles with known answers. The property
test at the end is the important one: it re-runs the whole backtest on a
truncated series and asserts the trades that already finished are unchanged.
If any part of the engine peeks at the future, that test fails.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ict.backtest import (
    Broker,
    CostModel,
    Order,
    RiskConfig,
    RiskManager,
    measure,
    position_size,
    report,
    run,
)
from ict.backtest.engine import BacktestResult
from ict.backtest.report import Metrics
from ict.cli import synthetic_candles

from .conftest import make_candles


def order(
    direction: str = "long",
    limit: float = 100.0,
    stop: float = 99.0,
    target: float = 103.0,
    placed: str = "2024-03-04 08:00",
    life_minutes: int = 20,
) -> Order:
    placed_at = pd.Timestamp(placed, tz="UTC")
    return Order(
        placed_at=placed_at,
        direction=direction,
        limit=limit,
        stop=stop,
        target=target,
        size=1.0,
        expires_at=placed_at + pd.Timedelta(minutes=life_minutes),
    )


def free_costs() -> CostModel:
    """No costs, so arithmetic tests measure only what they mean to."""
    return CostModel(fallback_spread=0.0, slippage=0.0, commission=0.0)


# --- the broker -------------------------------------------------------------


def test_an_order_cannot_fill_on_the_candle_it_was_placed_from():
    # The decision was made from this candle's close, so filling on it would
    # be acting on information from after the decision.
    candles = make_candles([(100, 101, 98, 100)], start="2024-03-04 08:00")
    broker = Broker(costs=free_costs())
    broker.place(order())

    broker.on_candle(candles.index[0], candles.iloc[0])

    assert broker.position is None
    assert broker.order is not None


def test_a_limit_order_fills_when_price_trades_through_it():
    candles = make_candles(
        [(100, 101, 98, 100), (100, 101, 99, 100)], start="2024-03-04 08:00"
    )
    broker = Broker(costs=free_costs())
    broker.place(order(limit=99.5))

    broker.on_candle(candles.index[1], candles.iloc[1])

    assert broker.position is not None
    assert broker.position.entry == 99.5


def test_an_unfilled_order_expires():
    rows = [(100, 101, 100.5, 100)] * 30
    candles = make_candles(rows, start="2024-03-04 08:00")
    broker = Broker(costs=free_costs())
    broker.place(order(limit=95.0, life_minutes=5))

    for stamp, candle in candles.iterrows():
        broker.on_candle(stamp, candle)

    assert broker.order is None
    assert broker.position is None
    assert broker.trades == []


def test_a_stop_and_a_target_on_one_candle_resolves_as_the_stop():
    # A candle does not say which it touched first, so the pessimistic
    # reading is taken. The optimistic one turns losers into winners.
    candles = make_candles(
        [
            (100, 100.2, 99.8, 100),
            (100, 100, 100, 100),
            (100, 104, 98, 100),  # spans both the target and the stop
        ],
        start="2024-03-04 08:00",
    )
    broker = Broker(costs=free_costs())
    broker.place(order(limit=100.0, stop=99.0, target=103.0))

    for stamp, candle in candles.iterrows():
        broker.on_candle(stamp, candle)

    assert len(broker.trades) == 1
    assert broker.trades[0].outcome == "stop"


def test_a_winning_long_pays_out_the_target():
    candles = make_candles(
        [
            (100, 100.2, 99.8, 100),
            (100, 100.1, 99.9, 100),  # fills at 100
            (100, 103.5, 99.9, 103),  # hits the target at 103
        ],
        start="2024-03-04 08:00",
    )
    broker = Broker(costs=free_costs())
    broker.place(order(limit=100.0, stop=99.0, target=103.0))

    for stamp, candle in candles.iterrows():
        broker.on_candle(stamp, candle)

    trade = broker.trades[0]
    assert trade.outcome == "target"
    assert trade.gross == pytest.approx(3.0)
    # Risked 1.0 to make 3.0, so three R.
    assert trade.r_multiple == pytest.approx(3.0)


def test_a_losing_short_is_measured_in_r_too():
    candles = make_candles(
        [
            (100, 100.2, 99.8, 100),
            (100, 100.1, 99.9, 100),
            (100, 101.5, 99.9, 101),
        ],
        start="2024-03-04 08:00",
    )
    broker = Broker(costs=free_costs())
    broker.place(
        order(direction="short", limit=100.0, stop=101.0, target=97.0)
    )

    for stamp, candle in candles.iterrows():
        broker.on_candle(stamp, candle)

    trade = broker.trades[0]
    assert trade.outcome == "stop"
    assert trade.r_multiple == pytest.approx(-1.0)


def test_only_one_position_at_a_time():
    broker = Broker(costs=free_costs())
    broker.place(order())
    with pytest.raises(RuntimeError, match="while one is live"):
        broker.place(order())


# --- costs ------------------------------------------------------------------


def test_stops_slip_and_targets_do_not():
    costs = CostModel(slippage=0.0002)

    # A long stopped out fills below its stop.
    assert costs.exit_price(100.0, "long", is_stop=True) == pytest.approx(99.9998)
    # A short stopped out fills above it.
    assert costs.exit_price(100.0, "short", is_stop=True) == pytest.approx(100.0002)
    # A target is a limit order: it fills at its price or not at all.
    assert costs.exit_price(100.0, "long", is_stop=False) == 100.0


def test_costs_make_an_otherwise_break_even_trade_a_loser():
    candles = make_candles(
        [
            (100, 100.2, 99.8, 100),
            (100, 100.1, 99.9, 100),
            (100, 103.5, 99.9, 103),
        ],
        start="2024-03-04 08:00",
    )
    costs = CostModel(fallback_spread=0.5, slippage=0.0, commission=0.25)
    broker = Broker(costs=costs)
    broker.place(order(limit=100.0, stop=99.0, target=103.0))

    for stamp, candle in candles.iterrows():
        broker.on_candle(stamp, candle)

    trade = broker.trades[0]
    assert trade.gross == pytest.approx(3.0)
    # 0.5 of spread plus 0.25 commission on each side.
    assert trade.costs == pytest.approx(1.0)
    assert trade.net == pytest.approx(2.0)


def test_the_spread_comes_from_the_data_when_it_is_there():
    costs = CostModel(fallback_spread=0.001)
    with_spread = pd.Series({"close": 1.0, "spread": 0.0004})
    without = pd.Series({"close": 1.0})

    assert costs.spread_at(with_spread) == pytest.approx(0.0004)
    assert costs.spread_at(without) == pytest.approx(0.001)


def test_a_wide_spread_blocks_entry():
    costs = CostModel(max_spread_multiple=2.0)
    assert costs.is_tradeable(0.0002, median_spread=0.0001)
    assert not costs.is_tradeable(0.00021, median_spread=0.0001)


# --- risk -------------------------------------------------------------------


def test_size_follows_from_the_stop():
    # Risking 0.5% of 10,000 is 50. A stop 2.0 away buys 25 units.
    assert position_size(10_000, 0.005, 2.0) == pytest.approx(25.0)
    # A wider stop buys fewer units, so the loss is the same either way.
    assert position_size(10_000, 0.005, 5.0) == pytest.approx(10.0)


def test_a_zero_stop_distance_buys_nothing():
    assert position_size(10_000, 0.005, 0.0) == 0.0


def test_the_daily_trade_cap_holds():
    manager = RiskManager(RiskConfig(one_loss_per_session=False), 10_000)
    manager.start_day("2024-03-04")

    assert manager.may_trade()
    manager.record(10.0)
    assert manager.may_trade()
    manager.record(10.0)
    assert not manager.may_trade()
    assert manager.blocked["daily trade cap"] == 1


def test_one_loss_ends_the_session():
    manager = RiskManager(RiskConfig(one_loss_per_session=True), 10_000)
    manager.start_day("2024-03-04")

    manager.record(-50.0)
    assert not manager.may_trade()
    assert manager.blocked["one loss per session"] == 1

    # A new day clears it.
    manager.start_day("2024-03-05")
    assert manager.may_trade()


def test_the_daily_loss_limit_holds():
    manager = RiskManager(
        RiskConfig(max_trades_per_day=10, one_loss_per_session=False), 10_000
    )
    manager.start_day("2024-03-04")
    manager.record(-201.0)  # over 2% of 10,000

    assert not manager.may_trade()
    assert manager.blocked["daily loss limit"] == 1


def test_a_deep_drawdown_pauses_trading():
    manager = RiskManager(
        RiskConfig(
            max_trades_per_day=100,
            one_loss_per_session=False,
            daily_loss_limit=1.0,  # isolate the drawdown rule from the daily one
        ),
        10_000,
    )
    manager.start_day("2024-03-04")
    manager.record(-700.0)  # 7%, past the 6% pause

    assert manager.paused
    assert not manager.may_trade()

    # A new week lifts it, as a human review would in the live system.
    manager.resume()
    manager.start_day("2024-03-11")
    assert manager.may_trade()


# --- metrics ----------------------------------------------------------------


def synthetic_result(nets: list[float], risk: float = 100.0) -> BacktestResult:
    """A result built from known net outcomes, for checking the arithmetic."""
    from ict.backtest.broker import Trade

    trades = []
    equity = 10_000.0
    stamps, values = [], []
    for index, net in enumerate(nets):
        stamp = pd.Timestamp("2024-03-04 08:00", tz="UTC") + pd.Timedelta(hours=index)
        trades.append(
            Trade(
                opened_at=stamp,
                closed_at=stamp,
                direction="long",
                entry=100.0,
                exit=100.0 + net / 1.0,
                stop=100.0 - risk,
                target=200.0,
                size=1.0,
                reason="",
                outcome="target" if net > 0 else "stop",
                gross=net,
                costs=0.0,
            )
        )
        equity += net
        stamps.append(stamp)
        values.append(equity)

    return BacktestResult(
        trades=trades,
        equity_curve=pd.Series(values, index=pd.DatetimeIndex(stamps)),
        starting_equity=10_000.0,
        final_equity=equity,
        candles=1000,
        days=10,
    )


def test_profit_factor_is_gross_profit_over_gross_loss():
    metrics = measure(synthetic_result([300.0, -100.0, -100.0]))
    assert metrics.gross_profit == pytest.approx(300.0)
    assert metrics.gross_loss == pytest.approx(200.0)
    assert metrics.profit_factor == pytest.approx(1.5)


def test_expectancy_is_the_mean_r_multiple():
    # Risk is 100 per trade, so +300 is 3R and -100 is -1R.
    metrics = measure(synthetic_result([300.0, -100.0, -100.0]))
    assert metrics.expectancy_r == pytest.approx((3 - 1 - 1) / 3)


def test_drawdown_is_measured_from_the_running_peak():
    # Up 500, then down 1,000: the peak was 10,500 and the trough 9,500.
    metrics = measure(synthetic_result([500.0, -1000.0]))
    assert metrics.max_drawdown == pytest.approx(1000 / 10_500)


def test_drawdown_counts_a_fall_from_the_starting_equity():
    metrics = measure(synthetic_result([-500.0]))
    assert metrics.max_drawdown == pytest.approx(0.05)


def test_no_trades_is_reported_not_crashed():
    empty = BacktestResult(
        trades=[],
        equity_curve=pd.Series(dtype="float64"),
        starting_equity=10_000.0,
        final_equity=10_000.0,
        candles=100,
        days=1,
    )
    metrics = measure(empty)
    assert metrics.trades == 0
    assert not metrics.passes
    assert "No trades were taken" in report(empty, metrics)


def test_the_gate_needs_all_four_criteria():
    # Good on three, short on trade count.
    nearly = Metrics(
        trades=199,
        wins=100,
        losses=99,
        win_rate=0.5,
        gross_profit=1000,
        gross_loss=500,
        profit_factor=2.0,
        expectancy_r=0.5,
        total_r=99.5,
        max_drawdown=0.05,
        net=500,
        return_pct=0.05,
        costs=10,
        average_win_r=2.0,
        average_loss_r=-1.0,
    )
    assert not nearly.passes
    failing = [name for name, ok, _ in nearly.gate() if not ok]
    assert failing == ["at least 200 trades"]


def test_the_report_keeps_the_caveats():
    result = synthetic_result([300.0, -100.0])
    text = report(result, measure(result), combinations_tried=40, verified=False)

    assert "Parameter combinations tried: 40" in text
    assert "inflates the chance of a lucky result" in text
    assert "have NOT passed the 90% hand labelling gate" in text


def test_a_verified_run_drops_the_unverified_warning():
    result = synthetic_result([300.0, -100.0])
    text = report(result, measure(result), verified=True)
    assert "have NOT passed" not in text


# --- the engine, end to end -------------------------------------------------


def test_a_run_produces_a_coherent_result():
    result = run(synthetic_candles(days=10))

    assert result.candles > 0
    assert result.days > 0
    frame = result.to_frame()
    if not frame.empty:
        # Equity must reconcile with the trades that produced it.
        assert result.final_equity == pytest.approx(
            result.starting_equity + frame["net"].sum()
        )


def test_every_trade_closes_by_the_end():
    result = run(synthetic_candles(days=8))
    frame = result.to_frame()
    if not frame.empty:
        assert frame["closed_at"].notna().all()
        assert (frame["closed_at"] >= frame["opened_at"]).all()


def test_entries_only_happen_in_silver_bullet_windows():
    from ict.timeframes.sessions import is_silver_bullet

    result = run(synthetic_candles(days=10))
    frame = result.to_frame()
    if frame.empty:
        pytest.skip("no trades in this fixture")

    opens = pd.DatetimeIndex(frame["opened_at"])
    assert is_silver_bullet(opens).all()


def test_an_empty_series_runs_without_trading():
    empty = synthetic_candles(days=1).iloc[:0]
    result = run(empty)
    assert result.trades == []
    assert result.final_equity == result.starting_equity


def test_the_backtest_does_not_look_ahead():
    """Re-running on truncated data must not change finished trades.

    This is the test that matters. If any part of the engine reads a candle
    that had not closed, the trades it produced with the full series will
    differ from the ones it produces when the future is simply not there.
    """
    candles = synthetic_candles(days=12)
    cut = candles.index[len(candles) * 2 // 3]

    full = run(candles).to_frame()
    truncated = run(candles.loc[candles.index <= cut]).to_frame()

    if full.empty:
        pytest.skip("no trades in this fixture")

    # Compare only trades that had finished before the cut: anything still
    # open at the cut is legitimately resolved differently.
    settled = full.loc[full["closed_at"] < cut].reset_index(drop=True)
    matching = truncated.loc[truncated["closed_at"] < cut].reset_index(drop=True)

    assert len(settled) == len(matching), "the set of finished trades changed"
    for column in ("opened_at", "closed_at", "direction", "entry", "exit", "outcome"):
        pd.testing.assert_series_equal(
            settled[column], matching[column], check_names=False
        )


def test_risk_limits_actually_bind_during_a_run():
    # One loss per session is on by default, so no day may show two losses.
    result = run(synthetic_candles(days=15))
    frame = result.to_frame()
    if frame.empty:
        pytest.skip("no trades in this fixture")

    frame["day"] = pd.DatetimeIndex(frame["opened_at"]).tz_convert(
        "America/New_York"
    ).date
    per_day = frame.groupby("day")["net"].apply(lambda s: (s < 0).sum())
    assert per_day.max() <= 1


def test_costs_reduce_the_result():
    candles = synthetic_candles(days=10)
    free = run(candles, costs=CostModel(fallback_spread=0.0, commission=0.0))
    charged = run(candles, costs=CostModel(fallback_spread=0.0005, commission=1.0))

    if not free.to_frame().empty and not charged.to_frame().empty:
        assert charged.final_equity < free.final_equity


def test_the_strategy_never_rests_an_order_at_a_spent_gap():
    """A gap price has already traded back into is not an entry.

    The imbalance is gone: resting a limit there waits for something that no
    longer exists. Before this was enforced, 82% of setups on the test data
    were built on gaps that had already been mitigated.
    """
    from ict.analysis import analyse
    from ict.backtest.silver_bullet import SilverBullet
    from ict.detectors.fvg import unmitigated
    from ict.timeframes.resample import resample

    candles = synthetic_candles(days=20)
    entry = analyse(candles, "1m")
    draw = analyse(resample(candles, "1h"), "1h")
    strategy = SilverBullet(entry, draw)

    checked = 0
    for now in candles.index[::7]:
        setup = strategy.find_setup(now, candles.loc[now])
        if setup is None:
            continue
        checked += 1
        live = unmitigated(entry.fvgs, now)
        at_limit = live.loc[
            (live["top"] == setup.limit) | (live["bottom"] == setup.limit)
        ]
        assert not at_limit.empty, f"order rested at a spent gap at {now}"

    if checked == 0:
        pytest.skip("no setups in this fixture")
