import pytest

from ict.config import FVGConfig, OrderBlockConfig
from ict.detectors.fvg import find_fvgs, unmitigated
from ict.detectors.order_blocks import find_order_blocks

from .conftest import make_candles


def _quiet(count: int, price: float = 100.0):
    return [(price, price + 0.2, price - 0.2, price)] * count


def test_bullish_fvg_is_the_gap_between_candle_one_and_three():
    # Candle 1 high 100.2, candle 3 low 101.0: a 0.8 wide bullish gap.
    rows = _quiet(20) + [
        (100.0, 100.2, 99.8, 100.1),
        (100.1, 102.0, 100.0, 101.8),
        (101.8, 102.4, 101.0, 102.2),
    ]
    candles = make_candles(rows)
    gaps = find_fvgs(candles, FVGConfig(min_gap_atr=0.0))
    bullish = gaps.loc[gaps["direction"] == "bullish"]

    assert len(bullish) == 1
    gap = bullish.iloc[0]
    assert gap["bottom"] == pytest.approx(100.2)
    assert gap["top"] == pytest.approx(101.0)
    # Timed at the third candle, which is when the gap can be known.
    assert gap["time"] == candles.index[-1]



def test_bearish_fvg():
    rows = _quiet(20) + [
        (100.0, 100.2, 99.8, 99.9),
        (99.9, 100.0, 98.0, 98.2),
        (98.2, 99.0, 97.6, 97.8),
    ]
    candles = make_candles(rows)
    gaps = find_fvgs(candles, FVGConfig(min_gap_atr=0.0))
    bearish = gaps.loc[gaps["direction"] == "bearish"]

    assert len(bearish) == 1
    assert bearish.iloc[0]["top"] == pytest.approx(99.8)
    assert bearish.iloc[0]["bottom"] == pytest.approx(99.0)


def test_overlapping_candles_leave_no_gap():
    rows = _quiet(20) + [
        (100.0, 101.0, 99.8, 100.8),
        (100.8, 101.5, 100.5, 101.2),
        (101.2, 101.8, 100.9, 101.6),  # low 100.9 is below candle 1's high
    ]
    candles = make_candles(rows)
    gaps = find_fvgs(candles, FVGConfig(min_gap_atr=0.0))

    # The triple under test ends on the last candle, and leaves no gap.
    assert gaps.loc[gaps["time"] == candles.index[-1]].empty


def test_tiny_gaps_are_filtered_by_the_atr_minimum():
    rows = _quiet(20) + [
        (100.0, 100.2, 99.8, 100.1),
        (100.1, 100.5, 100.0, 100.4),
        (100.4, 100.7, 100.21, 100.6),  # a 0.01 gap
    ]
    candles = make_candles(rows)

    assert not find_fvgs(candles, FVGConfig(min_gap_atr=0.0)).empty
    assert find_fvgs(candles, FVGConfig(min_gap_atr=0.5)).empty


def test_mitigation_is_recorded_when_price_returns():
    rows = _quiet(20) + [
        (100.0, 100.2, 99.8, 100.1),
        (100.1, 102.0, 100.0, 101.8),
        (101.8, 102.4, 101.0, 102.2),
        (102.2, 102.4, 100.5, 100.8),  # trades back into the gap
    ]
    candles = make_candles(rows)
    gap = find_fvgs(candles, FVGConfig(min_gap_atr=0.0)).iloc[0]

    assert gap["mitigated_at"] == candles.index[-1]
    assert unmitigated(find_fvgs(candles, FVGConfig(min_gap_atr=0.0)), candles.index[-2]).shape[0] == 1
    assert unmitigated(find_fvgs(candles, FVGConfig(min_gap_atr=0.0)), candles.index[-1]).empty


def test_inversion_is_a_close_clean_through_the_gap():
    rows = _quiet(20) + [
        (100.0, 100.2, 99.8, 100.1),
        (100.1, 102.0, 100.0, 101.8),
        (101.8, 102.4, 101.0, 102.2),
        (102.2, 102.4, 99.5, 99.6),  # closes below the gap's bottom
    ]
    candles = make_candles(rows)
    gap = find_fvgs(candles, FVGConfig(min_gap_atr=0.0)).iloc[0]

    assert gap["inverted_at"] == candles.index[-1]


def test_order_block_is_the_last_down_candle_before_an_up_leg():
    rows = _quiet(16) + [
        (100.0, 100.2, 99.8, 100.0),
        (100.0, 101.5, 99.9, 101.2),  # swing high at 101.5
        (101.2, 101.0, 100.4, 100.6),
        (100.6, 100.8, 100.2, 100.4),  # swing confirmed
        (100.4, 100.5, 99.6, 99.7),  # the last down candle: the block
        (99.7, 104.0, 99.6, 103.8),  # displacement that breaks 101.5
    ]
    candles = make_candles(rows)
    blocks = find_order_blocks(candles)

    assert len(blocks) >= 1
    block = blocks.loc[blocks["direction"] == "bullish"].iloc[0]
    assert block["time"] == candles.index[-2]
    assert block["top"] == pytest.approx(100.5)
    assert block["bottom"] == pytest.approx(99.6)
    assert block["mean_threshold"] == pytest.approx(100.05)


def test_no_order_block_without_a_structure_break():
    # A big up candle, but it breaks nothing, so there is no block.
    rows = _quiet(20) + [
        (100.0, 100.2, 99.4, 99.5),
        (99.5, 101.0, 99.4, 100.9),
    ]
    candles = make_candles(rows)
    assert find_order_blocks(candles).empty


def test_the_size_threshold_actually_filters():
    """The old default of 0.05 ATR rejected nothing at all.

    A threshold no gap ever falls below is not a filter, it is decoration.
    This pins that the default rejects a gap narrower than the spread it
    would have to be entered through.
    """
    from ict.config import FVGConfig as _FVGConfig

    assert _FVGConfig().min_gap_atr >= 0.15

    rows = _quiet(20) + [
        (100.0, 100.2, 99.8, 100.1),
        (100.1, 100.5, 100.0, 100.4),
        (100.4, 100.7, 100.25, 100.6),  # a 0.05 wide gap on a ~0.4 ATR
    ]
    candles = make_candles(rows)

    assert not find_fvgs(candles, FVGConfig(min_gap_atr=0.0)).empty
    # Too narrow to trade once the spread is paid.
    assert find_fvgs(candles, FVGConfig()).empty
