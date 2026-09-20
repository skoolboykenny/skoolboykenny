"""Tests for the news module: the calendar, the gate and the playbooks.

The gate is a risk check, so what is tested is that it blocks what it should
and nothing else, and that the vectorised form and the point in time form agree.
A gate that disagrees with itself would let a backtest and a live run take
different trades from the same rules.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ict.news import (
    DirectionalPlaybook,
    Event,
    NewsConfig,
    NewsCostModel,
    NewsGate,
    SpikeCorrectionPlaybook,
    events,
    gated_minutes,
    read_calendar,
    scaled_surprise,
)
from ict.news.calendar import _parse_impact, _parse_number


def write_calendar(tmp_path, rows, name="calendar.csv") -> str:
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


# --- parsing ----------------------------------------------------------------


def test_decorated_figures_are_scaled_not_stripped():
    """250K against a forecast of 0.25M is the same number."""
    assert _parse_number("250K") == pytest.approx(250_000)
    assert _parse_number("0.25M") == pytest.approx(250_000)
    assert _parse_number("-1.5B") == pytest.approx(-1.5e9)
    assert _parse_number("3.2%") == pytest.approx(3.2)
    assert _parse_number("1,234") == pytest.approx(1234)


def test_a_blank_figure_is_none_not_zero():
    """A release with no actual has not happened. Zero says it printed zero."""
    for blank in ("", "  ", "-", "--", "n/a", None):
        assert _parse_number(blank) is None


def test_impact_is_normalised_from_the_many_ways_calendars_say_it():
    assert _parse_impact("High") == "high"
    assert _parse_impact("3") == "high"
    assert _parse_impact("red") == "high"
    assert _parse_impact("High Impact Expected") == "high"
    assert _parse_impact("orange") == "medium"
    assert _parse_impact("anything else") == "low"


def test_a_calendar_is_read_into_utc_from_its_own_timezone(tmp_path):
    """Getting the source zone wrong shifts every gate by hours, silently."""
    path = write_calendar(tmp_path, [
        {"Date": "2024-03-08", "Time": "08:30", "Currency": "USD",
         "Impact": "High", "Event": "Non-Farm Payrolls",
         "Actual": "275K", "Forecast": "200K", "Previous": "229K"},
    ])
    frame = read_calendar(path, timezone="America/New_York")
    assert len(frame) == 1
    # 08:30 New York in March is 13:30 UTC.
    assert frame["time"].iloc[0] == pd.Timestamp("2024-03-08 13:30", tz="UTC")
    assert frame["actual"].iloc[0] == pytest.approx(275_000)


def test_a_calendar_can_be_filtered_to_the_currencies_that_matter(tmp_path):
    path = write_calendar(tmp_path, [
        {"Date": "2024-03-08", "Time": "08:30", "Currency": "USD",
         "Impact": "High", "Event": "NFP"},
        {"Date": "2024-03-08", "Time": "09:00", "Currency": "AUD",
         "Impact": "High", "Event": "RBA"},
    ])
    frame = read_calendar(path, currencies=("EUR", "USD"))
    assert list(frame["currency"]) == ["USD"]


def test_a_calendar_with_no_date_column_says_so(tmp_path):
    path = write_calendar(tmp_path, [{"Currency": "USD", "Event": "NFP"}])
    with pytest.raises(ValueError, match="no date or timestamp"):
        read_calendar(path)


# --- events -----------------------------------------------------------------


def test_surprise_is_none_before_the_release():
    """Reading a surprise before its release is reading the future."""
    scheduled = Event(
        pd.Timestamp("2024-03-08 13:30", tz="UTC"), "USD", "high", "NFP",
        actual=None, forecast=200_000, previous=229_000,
    )
    assert scheduled.surprise is None
    assert scheduled.expected_direction == -1  # forecast below previous


def test_a_revision_is_measured_against_the_previous_figure():
    event = Event(
        pd.Timestamp("2024-03-08 13:30", tz="UTC"), "USD", "high", "NFP",
        actual=275_000, forecast=200_000, previous=229_000, revised=180_000,
    )
    assert event.surprise == pytest.approx(75_000)
    assert event.revision == pytest.approx(49_000)


def test_tier_one_and_fomc_are_recognised():
    fomc = Event(pd.Timestamp("2024-03-20 18:00", tz="UTC"), "USD", "high",
                 "FOMC Statement")
    assert fomc.is_fomc and fomc.is_tier_one
    pmi = Event(pd.Timestamp("2024-03-20 14:00", tz="UTC"), "USD", "high",
                "Flash Services PMI")
    assert not pmi.is_fomc and not pmi.is_tier_one


def test_surprises_are_scaled_by_the_events_own_history():
    """A 0.1 CPI miss and a 0.1 NFP miss are not the same event."""
    frame = pd.DataFrame({
        "event": ["CPI"] * 10 + ["NFP"] * 10,
        "actual": list(np.arange(10) * 0.1) + list(np.arange(10) * 10_000.0),
        "forecast": [0.0] * 10 + [0.0] * 10,
    })
    scaled = scaled_surprise(frame, minimum_history=4)
    # Comparable units: neither event dominates purely by its quoting scale.
    cpi = scaled[:10].dropna()
    nfp = scaled[10:].dropna()
    assert len(cpi) and len(nfp)
    assert abs(cpi.iloc[-1] - nfp.iloc[-1]) < 0.5


def test_a_surprise_scale_never_uses_later_releases():
    """A 2021 release scaled by a spread including 2024 is lookahead."""
    frame = pd.DataFrame({
        "event": ["CPI"] * 6,
        "actual": [1.0, 1.0, 1.0, 1.0, 1.0, 100.0],
        "forecast": [0.0] * 6,
    })
    scaled = scaled_surprise(frame, minimum_history=4)
    # The huge final release must not inflate the scale of the ones before it.
    assert scaled.iloc[4] == pytest.approx(1.0)


def test_too_little_history_gives_no_scale_rather_than_a_guess():
    frame = pd.DataFrame({
        "event": ["Rare Event"] * 3, "actual": [1.0, 2.0, 3.0],
        "forecast": [0.0, 0.0, 0.0],
    })
    assert scaled_surprise(frame, minimum_history=8).isna().all()


# --- the gate ---------------------------------------------------------------


def calendar_frame(rows) -> pd.DataFrame:
    return pd.DataFrame([
        {"time": pd.Timestamp(t, tz="UTC"), "currency": c, "impact": i,
         "event": e, "actual": None, "forecast": None, "previous": None,
         "revised": None}
        for t, c, i, e in rows
    ])


def test_the_gate_blocks_fifteen_minutes_either_side():
    gate = NewsGate(calendar_frame([("2024-03-08 13:30", "USD", "high", "NFP")]))
    assert gate.blocked_at(pd.Timestamp("2024-03-08 13:14", tz="UTC")) is None
    assert gate.blocked_at(pd.Timestamp("2024-03-08 13:15", tz="UTC")) is not None
    assert gate.blocked_at(pd.Timestamp("2024-03-08 13:30", tz="UTC")) is not None
    assert gate.blocked_at(pd.Timestamp("2024-03-08 13:45", tz="UTC")) is not None
    assert gate.blocked_at(pd.Timestamp("2024-03-08 13:46", tz="UTC")) is None


def test_only_high_impact_releases_gate():
    gate = NewsGate(calendar_frame([
        ("2024-03-08 13:30", "USD", "medium", "Retail Sales"),
        ("2024-03-08 15:00", "USD", "low", "Speech"),
    ]))
    assert gate.blackouts == []


def test_the_gate_reads_both_currencies_of_a_pair():
    """EUR/USD is exposed to ECB and to the Fed."""
    gate = NewsGate(
        calendar_frame([
            ("2024-03-08 13:30", "USD", "high", "NFP"),
            ("2024-03-08 12:45", "EUR", "high", "ECB Rate"),
            ("2024-03-08 09:00", "AUD", "high", "RBA"),
        ]),
        instrument="EUR_USD",
    )
    assert len(gate.blackouts) == 2


def test_the_vectorised_and_point_in_time_forms_agree():
    """Disagreement means a backtest and a live run take different trades."""
    gate = NewsGate(calendar_frame([
        ("2024-03-08 13:30", "USD", "high", "NFP"),
        ("2024-03-08 15:00", "USD", "high", "FOMC"),
    ]))
    index = pd.date_range("2024-03-08 12:00", "2024-03-08 16:00", freq="1min", tz="UTC")
    vectorised = gate.mask(index)
    one_by_one = np.array([gate.blocked_at(t) is not None for t in index])
    assert np.array_equal(vectorised, one_by_one)


def test_overlapping_releases_do_not_unblock_each_other():
    """Two releases ten minutes apart make one longer window, not two holes."""
    gate = NewsGate(calendar_frame([
        ("2024-03-08 13:30", "USD", "high", "CPI"),
        ("2024-03-08 13:40", "USD", "high", "Core CPI"),
    ]))
    index = pd.date_range("2024-03-08 13:15", "2024-03-08 13:55", freq="1min", tz="UTC")
    assert gate.mask(index).all()


def test_no_calendar_means_nothing_is_gated_and_the_report_says_so():
    """An empty calendar is ignorance of releases, not absence of them."""
    gate = NewsGate(pd.DataFrame())
    assert gate.is_empty
    assert gate.blackouts == []
    assert "not the same" in gate.summary()


def test_fomc_can_block_a_whole_day_but_does_not_by_default():
    rows = calendar_frame([("2024-03-20 18:00", "USD", "high", "FOMC Statement")])
    assert len(NewsGate(rows).blackouts) == 1
    whole_day = NewsGate(rows, block_fomc_day=True)
    assert len(whole_day.blackouts) == 2
    # Mid-morning, far from the statement, is still blocked.
    assert whole_day.blocked_at(pd.Timestamp("2024-03-20 14:00", tz="UTC")) is not None


def test_gated_share_is_reported_so_a_gate_cannot_hide_its_size():
    """A gate blocking a third of the session is a different strategy."""
    gate = NewsGate(calendar_frame([("2024-03-08 13:30", "USD", "high", "NFP")]))
    index = pd.date_range("2024-03-08 13:00", "2024-03-08 14:00", freq="1min", tz="UTC")
    share = gated_minutes(gate, index)
    assert 0.4 < share < 0.6


# --- costs ------------------------------------------------------------------


def test_the_spread_is_widened_for_the_first_minute_then_decays():
    """A news backtest at normal spread tests a market that does not exist."""
    release = pd.Timestamp("2024-03-08 13:30", tz="UTC")
    costs = NewsCostModel(spike_multiple=4.0, release_times=(release,))

    assert costs.multiplier_at(release) == pytest.approx(4.0)
    assert costs.multiplier_at(release + pd.Timedelta(seconds=30)) == pytest.approx(2.5)
    assert costs.multiplier_at(release + pd.Timedelta(seconds=60)) == pytest.approx(1.0)
    assert costs.multiplier_at(release + pd.Timedelta(minutes=5)) == pytest.approx(1.0)
    assert costs.multiplier_at(release - pd.Timedelta(seconds=1)) == pytest.approx(1.0)


def test_a_candle_in_the_widened_window_pays_the_wider_spread():
    release = pd.Timestamp("2024-03-08 13:30", tz="UTC")
    costs = NewsCostModel(spike_multiple=4.0, release_times=(release,))
    candle = pd.Series({"spread": 0.0001}, name=release)
    assert costs.spread_at(candle) == pytest.approx(0.0004)


# --- playbooks --------------------------------------------------------------


def test_the_playbooks_are_not_in_the_ict_model_registry():
    """They are a separate strategy with their own record."""
    from ict.backtest import MODELS

    assert "news_directional" not in MODELS
    assert "news_spike_correction" not in MODELS


def test_a_scheduled_event_with_no_actual_is_not_tradeable():
    """A scheduled release is not a result."""
    from ict.backtest.strategy import build_context
    from ict.cli import synthetic_candles

    context = build_context(synthetic_candles(days=5))
    scheduled = Event(pd.Timestamp("2024-03-05 13:30", tz="UTC"), "USD", "high",
                      "NFP", actual=None, forecast=200_000, previous=229_000)
    playbook = DirectionalPlaybook(context, events=[scheduled])
    assert playbook.events == []


def test_a_release_is_only_live_after_it_has_happened():
    from ict.backtest.strategy import build_context
    from ict.cli import synthetic_candles

    context = build_context(synthetic_candles(days=5))
    release = pd.Timestamp("2024-03-05 13:30", tz="UTC")
    event = Event(release, "USD", "high", "NFP",
                  actual=275_000, forecast=200_000, previous=229_000)
    playbook = DirectionalPlaybook(context, NewsConfig(window_minutes=30),
                                   events=[event])

    assert playbook.live_event(release - pd.Timedelta(minutes=1)) is None
    assert playbook.live_event(release) is None  # the release minute itself
    assert playbook.live_event(release + pd.Timedelta(minutes=1)) is event
    assert playbook.live_event(release + pd.Timedelta(minutes=31)) is None


def test_a_surprise_with_too_little_history_produces_no_trade():
    from ict.backtest.strategy import build_context
    from ict.cli import synthetic_candles

    context = build_context(synthetic_candles(days=5))
    event = Event(pd.Timestamp("2024-03-05 13:30", tz="UTC"), "USD", "high",
                  "Rare Release", actual=1.0, forecast=0.0, previous=0.0)
    playbook = DirectionalPlaybook(context, events=[event])
    assert playbook.scaled_surprise(event) is None


def test_both_playbooks_run_through_the_normal_engine():
    from ict.backtest import run
    from ict.backtest.strategy import build_context
    from ict.cli import synthetic_candles

    candles = synthetic_candles(days=10)
    context = build_context(candles)
    releases = [
        Event(pd.Timestamp("2024-03-05 13:30", tz="UTC"), "USD", "high", "CPI",
              actual=3.4, forecast=3.1, previous=3.1),
        Event(pd.Timestamp("2024-03-06 13:30", tz="UTC"), "USD", "high", "CPI",
              actual=3.0, forecast=3.2, previous=3.4),
    ]
    for playbook in (DirectionalPlaybook, SpikeCorrectionPlaybook):
        model = playbook(context, events=releases)
        result = run(candles, strategy=model, context=context)
        assert result.parameters["model"] == playbook.name
