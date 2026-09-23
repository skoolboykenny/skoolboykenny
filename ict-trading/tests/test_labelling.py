"""Tests for the labelling page and the gate it feeds.

The page itself is driven in a browser separately. What is tested here is what
the page is built from and what comes out the other end: that the charts carry
no detector output, that the times it writes are the ones the scorer reads, and
that a chart reviewed but left blank still counts against a detector.
"""

from __future__ import annotations

import json
import re

import pandas as pd
import pytest

from ict.analysis import analyse
from ict.cli import synthetic_candles
from ict.config import MARKET_TZ
from ict.labelling import MARKERS, build_chart, build_page, plotly_script
from ict.verification import (
    CONCEPTS,
    ConceptScore,
    read_reviewed,
    score,
)


@pytest.fixture(scope="module")
def day():
    candles = synthetic_candles(days=5)
    local = candles.tz_convert(MARKET_TZ)
    first = sorted({s.date() for s in local.index})[1]
    start = pd.Timestamp(first, tz=MARKET_TZ)
    frame = local.loc[(local.index >= start) & (local.index < start + pd.Timedelta(days=1))]
    return str(first), frame.tz_convert("UTC")


# --- the chart data ---------------------------------------------------------


def test_a_chart_carries_candles_and_nothing_a_detector_found(day):
    date, frame = day
    chart = build_chart(frame, date, "1m")

    assert len(chart.times) == len(frame)
    assert len(chart.opens) == len(chart.closes) == len(frame)
    # Session levels and kill zones are read off the clock, not inferred, so
    # they are allowed. Anything a detector decided is not.
    assert set(vars(chart)) == {
        "date", "timeframe", "times", "opens", "highs", "lows", "closes",
        "levels", "zones",
    }


def test_times_are_new_york_wall_clock_which_is_what_the_scorer_reads(day):
    """The page never converts a timezone, so it cannot get one wrong."""
    date, frame = day
    chart = build_chart(frame, date, "1m")

    first_local = frame.index[0].tz_convert(MARKET_TZ)
    written = pd.Timestamp(chart.times[0], unit="ms")
    assert written.hour == first_local.hour
    assert written.minute == first_local.minute


def test_every_concept_the_scorer_knows_has_a_key_on_the_page():
    """A concept with no key cannot be marked, so it can never be scored."""
    assert {concept for concept, _, _, _ in MARKERS} == set(CONCEPTS)


def test_the_keys_are_all_different():
    keys = [key for _, key, _, _ in MARKERS]
    assert len(set(keys)) == len(keys)


# --- the page ---------------------------------------------------------------


def test_the_page_embeds_its_charts_and_needs_no_network(day):
    date, frame = day
    page = build_page([build_chart(frame, date, "1m")])

    # The string appears inside the Plotly bundle's own config defaults, so
    # what matters is that nothing is *fetched*: no script tag with a src.
    assert "<script src=" not in page
    assert "Plotly.react" in page
    assert date in page


def test_the_plotly_bundle_is_inlined():
    """Labelling is a long offline job; a page that needs the network fails."""
    script = plotly_script()
    assert script.startswith("<script>")
    assert len(script) > 1_000_000


def test_the_page_shows_no_detector_output(day):
    """Someone who can see the answers will agree with them."""
    date, frame = day
    analysis = analyse(frame, with_levels=True)
    page = build_page([build_chart(frame, date, "1m")])

    assert not analysis.swings.empty
    payload = re.search(r'const CHARTS = (\[.*?\]);', page, re.S).group(1)
    data = json.loads(payload)

    # The payload holds candles and clock-derived furniture, and nothing a
    # detector decided.
    assert set(data[0]) == {
        "date", "timeframe", "t", "o", "h", "l", "c", "levels", "zones"
    }
    for name in ("swings", "sweeps", "shifts", "fvgs", "order_blocks", "pools"):
        assert f'"{name}"' not in payload

    # The prices the detectors found must not be sitting in the levels list
    # under another name.
    swing_prices = {round(float(p), 5) for p in analysis.swings["price"]}
    drawn = {round(float(lv["price"]), 5) for lv in data[0]["levels"]}
    assert len(drawn & swing_prices) <= 2  # a session level may coincide


def test_the_page_offers_a_way_to_say_nothing_is_here(day):
    """A chart with nothing on it is a real answer and the gate needs it."""
    date, frame = day
    page = build_page([build_chart(frame, date, "1m")])
    assert "Nothing here" in page
    assert "reviewed.csv" in page


def test_the_page_saves_work_as_it_goes(day):
    date, frame = day
    page = build_page([build_chart(frame, date, "1m")])
    assert "localStorage" in page


# --- the gate ---------------------------------------------------------------


def analyses_for(frame, date, timeframe="1m"):
    return {(date, timeframe): analyse(frame, timeframe=timeframe,
                                       with_levels=timeframe == "1m")}


def labels_frame(rows) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["date", "timeframe", "concept", "time_utc"])
    return frame


def test_a_chart_reviewed_and_left_blank_still_counts_detections(day):
    """The failure the gate exists to catch, and could not see.

    A detector that over-fires on quiet days contributed nothing to the score,
    because a chart with no labels was skipped entirely.
    """
    date, frame = day
    analyses = analyses_for(frame, date)
    detected = len(analyses[(date, "1m")].swings)
    assert detected > 0

    # One label on a different, unknown day, so this chart carries none.
    labels = labels_frame([
        ("1999-01-01", "1m", "swing_high",
         pd.Timestamp("1999-01-01 12:00", tz="UTC")),
    ])

    without = score(labels, analyses, pd.Timedelta(minutes=2))
    assert without[0].detected == 0  # the blank chart is invisible

    with_reviewed = score(
        labels, analyses, pd.Timedelta(minutes=2), reviewed={(date, "1m")}
    )
    assert with_reviewed[0].detected > 0
    assert with_reviewed[0].agreement == 0.0


def test_reviewed_does_not_change_a_chart_that_was_labelled(day):
    date, frame = day
    analyses = analyses_for(frame, date)
    swings = analyses[(date, "1m")].swings
    stamp = pd.Timestamp(swings["time"].iloc[0])

    labels = labels_frame([(date, "1m", "swing_high", stamp)])
    without = score(labels, analyses, pd.Timedelta(minutes=2))
    with_reviewed = score(
        labels, analyses, pd.Timedelta(minutes=2), reviewed={(date, "1m")}
    )
    assert without[0].detected == with_reviewed[0].detected
    assert without[0].matched == with_reviewed[0].matched


def test_reading_a_reviewed_file(tmp_path):
    path = tmp_path / "reviewed.csv"
    path.write_text("date,timeframe\n2024-03-08,15m\n2024-03-11,15m\n")
    assert read_reviewed(str(path)) == {("2024-03-08", "15m"), ("2024-03-11", "15m")}


def test_a_reviewed_file_missing_columns_says_so(tmp_path):
    path = tmp_path / "reviewed.csv"
    path.write_text("day,tf\n2024-03-08,15m\n")
    with pytest.raises(ValueError, match="missing columns"):
        read_reviewed(str(path))


def test_the_gate_still_fails_a_detector_that_fires_too_often():
    """Perfect recall must not be enough: precision is what the gate is for."""
    perfect_recall = ConceptScore("sweep", labelled=10, detected=100, matched=10)
    assert perfect_recall.recall == 1.0
    assert not perfect_recall.passes
