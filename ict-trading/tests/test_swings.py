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


def test_a_run_of_equal_highs_is_one_swing_at_its_last_candle():
    """Real feeds quantise prices, so adjacent equal highs are common.

    The strict rule discarded them entirely. Equal highs are also the
    liquidity pattern ICT cares most about, so throwing them away is the
    opposite of what the detector is for.
    """
    candles = make_candles(
        [
            (10, 11, 9, 10),
            (10, 12, 9, 11),
            (11, 15, 10, 14),  # the plateau starts
            (14, 15, 13, 14),  # same high
            (14, 15, 13, 14),  # same high again
            (14, 13, 11, 12),
            (12, 12, 10, 11),
        ]
    )
    swings = find_swings(candles, SwingConfig(n=2))
    highs = swings.loc[swings["kind"] == "high"]

    assert len(highs) == 1, "a plateau is one swing, not three and not none"
    assert highs.iloc[0]["price"] == 15
    # Marked at the last candle of the run, which is when it is confirmable.
    assert highs.iloc[0]["time"] == candles.index[4]


def test_the_strict_rule_loses_the_plateau_entirely():
    candles = make_candles(
        [
            (10, 11, 9, 10),
            (10, 12, 9, 11),
            (11, 15, 10, 14),
            (14, 15, 13, 14),
            (14, 15, 13, 14),
            (14, 13, 11, 12),
            (12, 12, 10, 11),
        ]
    )
    strict = find_swings(candles, SwingConfig(n=2, allow_plateaus=False))
    assert strict.loc[strict["kind"] == "high"].empty


def test_a_flat_stretch_does_not_make_a_swing_on_every_candle():
    # The failure the strict rule was guarding against. Still guarded.
    candles = make_candles([(10, 12, 9, 11)] * 9)
    swings = find_swings(candles, SwingConfig(n=2))
    assert swings.empty


def test_swings_survive_a_coarsely_quantised_feed():
    """USD/JPY quotes to three decimals and futures quote in ticks.

    On raw floats adjacent candles almost never share a high, so a strict
    rule looks fine. Quantise the same prices and it collapses.
    """
    import numpy as np

    rng = np.random.default_rng(4)
    walk = 150.0 + np.cumsum(rng.normal(0, 0.01, 400))
    rows = [
        (p, p + 0.02, p - 0.02, p + 0.005) for p in walk
    ]
    raw = make_candles(rows)
    coarse = raw.copy()
    coarse[["open", "high", "low", "close"]] = coarse[
        ["open", "high", "low", "close"]
    ].round(1)

    plateaus = len(find_swings(coarse, SwingConfig(n=2)))
    strict = len(find_swings(coarse, SwingConfig(n=2, allow_plateaus=False)))
    on_floats = len(find_swings(raw, SwingConfig(n=2)))

    # The strict rule loses most of them once prices tie.
    assert strict < on_floats * 0.6
    # Allowing plateaus keeps the detector usable on that feed.
    assert plateaus > strict * 1.5
