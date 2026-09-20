import pandas as pd

from ict.config import LiquidityConfig, SwingConfig
from ict.detectors.liquidity import find_pools, find_sweeps, unswept
from ict.detectors.swings import find_swings

from .conftest import make_candles

# A run that builds a swing high at 15, then wicks through it and closes back
# under: the textbook sweep of buy side liquidity.
SWEEP_SEQUENCE = [
    (10, 11, 9, 10),
    (10, 12, 9, 11),
    (11, 15, 10, 14),  # 2: swing high at 15
    (14, 13, 11, 12),
    (12, 12, 10, 11),  # 4: swing confirmed here
    (11, 12, 10, 11),
    (11, 17, 10, 11),  # 6: wick to 17, closes back at 11, under the pool
    (11, 12, 10, 11),
]


def test_pool_forms_at_a_swing_high():
    candles = make_candles(SWEEP_SEQUENCE)
    pools = find_pools(candles)
    buy_side = pools.loc[pools["side"] == "buy"]

    assert not buy_side.empty
    assert 15 in set(buy_side["price"])


def test_sweep_is_detected_and_timed_at_the_wick():
    candles = make_candles(SWEEP_SEQUENCE)
    sweeps = find_sweeps(candles)
    taken = sweeps.loc[sweeps["pool_price"] == 15]

    assert len(taken) == 1
    sweep = taken.iloc[0]
    assert sweep["side"] == "buy"
    assert sweep["time"] == candles.index[6]
    assert sweep["extreme"] == 17
    assert sweep["closed_back_at"] == candles.index[6]


def test_trading_through_and_staying_through_is_not_a_sweep():
    # Same setup, but price closes above the pool and stays there.
    sequence = SWEEP_SEQUENCE[:6] + [
        (11, 17, 10, 16),
        (16, 18, 16, 17),
        (17, 19, 16, 18),
        (18, 19, 17, 18),
    ]
    candles = make_candles(sequence)
    sweeps = find_sweeps(candles)

    assert sweeps.loc[sweeps["pool_price"] == 15].empty


def test_close_back_outside_the_window_does_not_confirm():
    # Wicks through, but only closes back inside six candles later, well past
    # the three candle window.
    sequence = SWEEP_SEQUENCE[:6] + [
        (11, 17, 10, 16),
        (16, 17, 15.5, 16),
        (16, 17, 15.5, 16),
        (16, 17, 15.5, 16),
        (16, 17, 15.5, 16),
        (16, 17, 10, 11),
    ]
    candles = make_candles(sequence)
    sweeps = find_sweeps(candles, config=LiquidityConfig(sweep_close_back_within=3))

    assert sweeps.loc[sweeps["pool_price"] == 15].empty


def test_equal_highs_cluster_into_one_pool():
    # Two swing highs a hair apart should be one pool, marked as equal highs.
    candles = make_candles(
        [
            (10, 11, 9, 10),
            (10, 12, 9, 11),
            (11, 15.00, 10, 14),
            (14, 13, 11, 12),
            (12, 12, 10, 11),
            (11, 12, 10, 11),
            (11, 15.01, 10, 14),
            (14, 13, 11, 12),
            (12, 12, 10, 11),
        ]
    )
    # A generous tolerance so the two highs are treated as equal.
    pools = find_pools(candles, config=LiquidityConfig(equal_tolerance_atr=2.0))
    buy_side = pools.loc[pools["side"] == "buy"]

    # Two rows, but one cluster: the pool before and after the second high
    # joined it. Each row is that pool as it stood at its own created_at.
    assert buy_side["cluster"].nunique() == 1
    assert len(buy_side) == 2

    first, second = buy_side.iloc[0], buy_side.iloc[1]
    assert int(first["touches"]) == 1
    assert bool(first["is_equal_highs"]) is False
    assert int(second["touches"]) == 2
    assert bool(second["is_equal_highs"]) is True

    # Collapsed to a point in time, it is one pool again.
    live = unswept(pools, candles.index[-1])
    assert len(live.loc[live["side"] == "buy"]) == 1


def test_a_pool_does_not_disappear_from_its_own_past():
    """Extending a pool later must not hide it from earlier.

    A pool formed on one day and widened on another used to record only the
    later time, so asking "what did I know then" on the first day found
    nothing. That made the answer depend on how much future data was loaded.
    """
    candles = make_candles(
        [
            (10, 11, 9, 10),
            (10, 12, 9, 11),
            (11, 15.00, 10, 14),  # first high
            (14, 13, 11, 12),
            (12, 12, 10, 11),  # confirmed here
            (11, 12, 10, 11),
            (11, 15.01, 10, 14),  # second high joins the cluster
            (14, 13, 11, 12),
            (12, 12, 10, 11),
        ]
    )
    pools = find_pools(candles, config=LiquidityConfig(equal_tolerance_atr=2.0))

    # As at the fifth candle, only the first high exists, and it must be there.
    early = unswept(pools, candles.index[4])
    early_buy = early.loc[early["side"] == "buy"]
    assert len(early_buy) == 1
    assert int(early_buy.iloc[0]["touches"]) == 1


def test_unswept_excludes_pools_already_taken():
    candles = make_candles(SWEEP_SEQUENCE)
    pools = find_pools(candles)

    before = unswept(pools, candles.index[5])
    after = unswept(pools, candles.index[7])

    assert 15 in set(before.loc[before["side"] == "buy", "price"])
    assert 15 not in set(after.loc[after["side"] == "buy", "price"])


def test_unswept_excludes_pools_that_do_not_exist_yet():
    candles = make_candles(SWEEP_SEQUENCE)
    pools = find_pools(candles)

    # The pool is confirmed at candle 4; at candle 3 it cannot be known.
    assert unswept(pools, candles.index[3]).empty
