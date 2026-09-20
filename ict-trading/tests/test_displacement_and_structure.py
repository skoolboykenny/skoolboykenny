import pytest

from ict.config import DisplacementConfig, StructureConfig
from ict.detectors.displacement import displacement_mask, find_displacements
from ict.detectors.liquidity import find_sweeps
from ict.detectors.structure import (
    find_breaks_of_structure,
    find_market_structure_shifts,
)

from .conftest import make_candles


def _quiet(count: int, price: float = 100.0) -> list[tuple[float, float, float, float]]:
    """Small, balanced candles that establish a low ATR."""
    return [(price, price + 0.2, price - 0.2, price)] * count


def test_large_clean_body_is_displacement():
    rows = _quiet(20) + [(100.0, 105.2, 99.9, 105.0)]
    candles = make_candles(rows)
    mask = displacement_mask(candles, DisplacementConfig())

    assert bool(mask.iloc[-1]) is True


def test_large_range_with_a_huge_wick_is_not_displacement():
    # Same high-to-low span as the candle above, but it gave it all back: the
    # body is a fraction of the range, so it is indecision, not intent.
    rows = _quiet(20) + [(100.0, 105.2, 99.9, 100.3)]
    candles = make_candles(rows)
    mask = displacement_mask(candles, DisplacementConfig())

    assert bool(mask.iloc[-1]) is False


def test_quiet_candles_never_displace():
    candles = make_candles(_quiet(30))
    assert not displacement_mask(candles, DisplacementConfig()).any()


def test_displacement_records_its_measurements():
    rows = _quiet(20) + [(100.0, 105.2, 99.9, 105.0)]
    candles = make_candles(rows)
    found = find_displacements(candles)

    assert len(found) == 1
    event = found.iloc[0]
    assert event["direction"] == "up"
    assert event["body"] == pytest.approx(5.0)
    assert event["body_atr"] > 1.5
    assert event["body_fraction"] > 0.5



def test_break_of_structure_is_a_close_beyond_the_last_swing():
    candles = make_candles(
        [
            (10, 11, 9, 10),
            (10, 12, 9, 11),
            (11, 15, 10, 14),  # swing high at 15
            (14, 13, 11, 12),
            (12, 12, 10, 11),  # confirmed here
            (11, 16, 10, 15.5),  # closes above 15
        ]
    )
    breaks = find_breaks_of_structure(candles)
    up = breaks.loc[breaks["direction"] == "up"]

    assert len(up) == 1
    assert up.iloc[0]["level"] == 15
    assert up.iloc[0]["time"] == candles.index[5]


def test_a_wick_through_a_swing_is_not_a_break():
    candles = make_candles(
        [
            (10, 11, 9, 10),
            (10, 12, 9, 11),
            (11, 15, 10, 14),
            (14, 13, 11, 12),
            (12, 12, 10, 11),
            (11, 16, 10, 14.5),  # wick above 15, closes back under
        ]
    )
    breaks = find_breaks_of_structure(candles)
    assert breaks.loc[breaks["direction"] == "up"].empty


def test_mss_needs_a_sweep_and_displacement():
    # Quiet base, a swing low taken, then a displaced close above the last
    # swing high: an upward market structure shift.
    rows = (
        _quiet(16)
        + [
            (100.0, 100.2, 99.8, 100.0),
            (100.0, 101.5, 99.9, 101.2),  # swing high at 101.5
            (101.2, 101.0, 100.4, 100.6),
            (100.6, 100.8, 100.2, 100.4),  # swing high confirmed
            (100.4, 100.6, 99.0, 99.2),  # swing low at 99.0
            (99.2, 99.8, 99.1, 99.6),
            (99.6, 99.9, 99.3, 99.7),  # swing low confirmed
            (99.7, 99.9, 98.5, 99.7),  # sweeps the 99.0 low, closes back above
            (99.7, 103.0, 99.6, 102.8),  # displaced close above 101.5
        ]
    )
    candles = make_candles(rows)
    sweeps = find_sweeps(candles)
    shifts = find_market_structure_shifts(candles, sweeps=sweeps)

    assert not shifts.empty
    shift = shifts.iloc[0]
    assert shift["direction"] == "up"
    assert shift["sweep_side"] == "sell"
    assert shift["sweep_time"] < shift["time"]


def test_no_shift_without_displacement():
    # The same sweep, but price creeps above the swing high instead of
    # displacing through it.
    rows = (
        _quiet(16)
        + [
            (100.0, 100.2, 99.8, 100.0),
            (100.0, 101.5, 99.9, 101.2),
            (101.2, 101.0, 100.4, 100.6),
            (100.6, 100.8, 100.2, 100.4),
            (100.4, 100.6, 99.0, 99.2),
            (99.2, 99.8, 99.1, 99.6),
            (99.6, 99.9, 99.3, 99.7),
            (99.7, 99.9, 98.5, 99.7),
            (99.7, 100.4, 99.6, 100.2),
            (100.2, 100.8, 100.0, 100.6),
            (100.6, 101.2, 100.4, 101.0),
            (101.0, 101.8, 100.9, 101.6),  # above 101.5, but only just
        ]
    )
    candles = make_candles(rows)
    sweeps = find_sweeps(candles)
    shifts = find_market_structure_shifts(candles, sweeps=sweeps)

    assert shifts.empty


def test_shift_must_follow_the_sweep_within_the_lookback():
    rows = (
        _quiet(16)
        + [
            (100.0, 100.2, 99.8, 100.0),
            (100.0, 101.5, 99.9, 101.2),
            (101.2, 101.0, 100.4, 100.6),
            (100.6, 100.8, 100.2, 100.4),
            (100.4, 100.6, 99.0, 99.2),
            (99.2, 99.8, 99.1, 99.6),
            (99.6, 99.9, 99.3, 99.7),
            (99.7, 99.9, 98.5, 99.7),  # the sweep
        ]
        + _quiet(10, 99.7)
        + [(99.7, 103.0, 99.6, 102.8)]  # displacement, but far too late
    )
    candles = make_candles(rows)
    sweeps = find_sweeps(candles)
    shifts = find_market_structure_shifts(
        candles, sweeps=sweeps, config=StructureConfig(sweep_lookback=3)
    )

    assert shifts.empty
