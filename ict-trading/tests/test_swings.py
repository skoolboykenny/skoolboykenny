import pandas as pd

from ict.config import SwingConfig
from ict.detectors.swings import confirmed_by, find_swings, last_swing

from .conftest import make_candles


def test_finds_a_single_obvious_swing_high():
    # Highs rise to a peak at index 2 and fall away: one swing high, n=2.
    candles = make_candles(
        [
            (10, 11, 9, 10),
            (10, 12, 9, 11),
            (11, 15, 10, 14),  # the peak
            (14, 13, 11, 12),
            (12, 12, 10, 11),
        ]
    )
    swings = find_swings(candles, SwingConfig(n=2))
    highs = swings.loc[swings["kind"] == "high"]

    assert len(highs) == 1
    assert highs.iloc[0]["price"] == 15
    assert highs.iloc[0]["time"] == candles.index[2]


def test_swing_is_confirmed_n_candles_later():
    candles = make_candles(
        [
            (10, 11, 9, 10),
            (10, 12, 9, 11),
            (11, 15, 10, 14),
            (14, 13, 11, 12),
            (12, 12, 10, 11),
        ]
    )
    swing = find_swings(candles, SwingConfig(n=2)).iloc[0]

    # It formed at candle 2 but could not be known until candle 4 closed.
    assert swing["time"] == candles.index[2]
    assert swing["confirmed_at"] == candles.index[4]


def test_equal_highs_do_not_make_a_swing():
    # Ties are excluded, so a flat top does not produce a swing on every candle.
    candles = make_candles(
        [
            (10, 11, 9, 10),
            (10, 12, 9, 11),
            (11, 12, 10, 11),
            (11, 12, 10, 11),
            (11, 11, 9, 10),
        ]
    )
    swings = find_swings(candles, SwingConfig(n=2))
    assert swings.loc[swings["kind"] == "high"].empty


def test_finds_swing_low():
    candles = make_candles(
        [
            (10, 11, 9, 10),
            (10, 10, 8, 9),
            (9, 9, 5, 6),  # the trough
            (6, 8, 7, 8),
            (8, 10, 8, 9),
        ]
    )
    lows = find_swings(candles, SwingConfig(n=2))
    low = last_swing(lows, "low")

    assert low is not None
    assert low["price"] == 5


def test_confirmed_by_filters_out_unconfirmed_swings():
    candles = make_candles(
        [
            (10, 11, 9, 10),
            (10, 12, 9, 11),
            (11, 15, 10, 14),
            (14, 13, 11, 12),
            (12, 12, 10, 11),
        ]
    )
    swings = find_swings(candles, SwingConfig(n=2))

    # One candle before confirmation, the swing must not be visible.
    assert confirmed_by(swings, candles.index[3]).empty
    assert len(confirmed_by(swings, candles.index[4])) == 1


def test_too_few_candles_returns_empty_frame_not_an_error():
    swings = find_swings(make_candles([(10, 11, 9, 10)]), SwingConfig(n=2))
    assert swings.empty
    assert list(swings.columns) == ["time", "price", "kind", "confirmed_at"]


def test_n_controls_strictness():
    # A minor peak survives n=1 but is not a swing at n=3.
    candles = make_candles(
        [
            (10, 12, 9, 10),
            (10, 11, 9, 10),
            (10, 13, 9, 12),
            (12, 11, 9, 10),
            (10, 14, 9, 13),
            (13, 12, 9, 10),
            (10, 11, 9, 10),
        ]
    )
    loose = find_swings(candles, SwingConfig(n=1))
    strict = find_swings(candles, SwingConfig(n=3))

    loose_highs = set(loose.loc[loose["kind"] == "high", "price"])
    strict_highs = set(strict.loc[strict["kind"] == "high", "price"])

    assert 13 in loose_highs
    assert 13 not in strict_highs
