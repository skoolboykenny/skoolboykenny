"""Tests for the dashboard.

Rendering is checked in a browser separately. What is tested here is the part
that would quietly mislead someone: the numbers, what the page claims about
where they came from, and the fact that a page meant to be shared carries no
way to touch a live account.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from ict.dashboard import (
    PALETTE,
    Dashboard,
    Gate,
    breakdown_svg,
    build,
    build_page,
    daily_svg,
    default_gates,
    equity_svg,
    summarise,
)
from ict.journal import Entry, Journal, read_journal


def entry(net: float = 100.0, r: float = 2.0, **overrides) -> Entry:
    fields = {
        "closed_at": pd.Timestamp("2024-03-08 15:00", tz="UTC"),
        "opened_at": pd.Timestamp("2024-03-08 14:00", tz="UTC"),
        "instrument": "EUR_USD",
        "model": "silver_bullet",
        "direction": "long",
        "entry": 1.0850, "exit": 1.0870, "stop": 1.0840, "target": 1.0880,
        "size": 1000.0, "outcome": "target",
        "gross": net, "costs": 0.0, "net": net, "r_multiple": r,
        "session": "ny_am", "reason": "test", "source": "backtest",
    }
    fields.update(overrides)
    return Entry(**fields)


def journal_of(rows, tmp_path) -> pd.DataFrame:
    book = Journal(path=tmp_path / "j.csv")
    for kwargs in rows:
        book.append(entry(**kwargs))
    return read_journal(tmp_path / "j.csv")


# --- the numbers ------------------------------------------------------------


def test_the_headline_numbers(tmp_path):
    frame = journal_of(
        [
            {"net": 200.0, "r": 2.0},
            {"net": -100.0, "r": -1.0, "closed_at": pd.Timestamp("2024-03-09 15:00", tz="UTC")},
            {"net": -100.0, "r": -1.0, "closed_at": pd.Timestamp("2024-03-10 15:00", tz="UTC")},
        ],
        tmp_path,
    )
    stats = summarise(frame)
    assert stats["trades"] == 3
    assert stats["total_r"] == pytest.approx(0.0)
    assert stats["expectancy_r"] == pytest.approx(0.0)
    assert stats["win_rate"] == pytest.approx(1 / 3)
    assert stats["profit_factor"] == pytest.approx(1.0)


def test_drawdown_is_measured_from_the_peak_not_the_start(tmp_path):
    """Up then down must show a drawdown even if the run ends in profit."""
    frame = journal_of(
        [
            {"net": 2000.0, "r": 2.0},
            {"net": -1000.0, "r": -1.0,
             "closed_at": pd.Timestamp("2024-03-09 15:00", tz="UTC")},
        ],
        tmp_path,
    )
    stats = summarise(frame)
    assert stats["total_r"] == pytest.approx(1.0)
    # Peak 12,000, trough 11,000, so 1/12.
    assert stats["max_drawdown"] == pytest.approx(1000 / 12000, abs=1e-4)


def test_an_empty_journal_summarises_to_nothing():
    assert summarise(pd.DataFrame()) == {"trades": 0}


# --- the charts -------------------------------------------------------------


def test_every_chart_survives_an_empty_journal():
    for svg in (equity_svg(pd.DataFrame()), daily_svg(pd.DataFrame())):
        assert "<svg" in svg
        assert "No trades yet" in svg
    assert breakdown_svg(pd.DataFrame(), "model", "x") == ""


def test_the_equity_chart_starts_at_zero_not_at_the_first_trade(tmp_path):
    """A curve beginning at its first result hides that result."""
    frame = journal_of([{"net": 500.0, "r": 5.0}], tmp_path)
    svg = equity_svg(frame)
    hover = re.search(r"data-hover='(\[.*?\])'", svg).group(1)
    assert hover.count('"r"') == 1  # one trade, but two plotted points
    assert svg.count("M") >= 1


def test_the_single_series_chart_has_no_legend(tmp_path):
    """One series, so the caption names it and there is no box to decode."""
    frame = journal_of([{"net": 100.0, "r": 1.0}], tmp_path)
    svg = equity_svg(frame)
    assert "legend" not in svg.lower()
    assert "Cumulative R" in svg


def test_bars_carry_a_native_title_so_hover_works_without_script(tmp_path):
    frame = journal_of([{"net": 100.0, "r": 1.0}], tmp_path)
    assert "<title>" in daily_svg(frame)


def test_a_breakdown_labels_every_row_directly(tmp_path):
    frame = journal_of(
        [
            {"net": 100.0, "r": 1.0, "model": "silver_bullet"},
            {"net": -50.0, "r": -0.5, "model": "turtle_soup"},
        ],
        tmp_path,
    )
    svg = breakdown_svg(frame, "model", "Total R by model")
    assert "silver_bullet" in svg and "turtle_soup" in svg
    assert "+1.00R" in svg and "-0.50R" in svg


def test_a_breakdown_names_trades_outside_a_kill_zone(tmp_path):
    """They must not be dropped, or the rows do not add up to the total."""
    frame = journal_of(
        [
            {"net": 100.0, "r": 1.0, "session": "ny_am"},
            {"net": -50.0, "r": -0.5, "session": ""},
        ],
        tmp_path,
    )
    assert "outside a kill zone" in breakdown_svg(frame, "session", "By session")


# --- what the page claims ---------------------------------------------------


def test_a_page_with_no_live_trades_says_so_at_the_top(tmp_path):
    frame = journal_of([{"net": 100.0, "r": 1.0, "source": "backtest"}], tmp_path)
    page = build_page(Dashboard(journal=frame, sources=["backtest"],
                                gates=default_gates(frame)))
    assert "No live money in this record" in page
    assert page.index("No live money") < page.index("Cumulative R")


def test_the_gates_come_before_the_results(tmp_path):
    """A dashboard that leads with profit and buries the gates is the genre
    this project is trying not to be in."""
    frame = journal_of([{"net": 100.0, "r": 1.0}], tmp_path)
    page = build_page(Dashboard(journal=frame, gates=default_gates(frame)))
    assert "Validation gates" in page
    assert page.index("Validation gates") < page.index("Results")
    assert page.index("Validation gates") < page.index("Cumulative R")


def test_no_gate_is_passed_by_the_absence_of_a_failure():
    gates = default_gates(pd.DataFrame())
    assert len(gates) == 6
    assert all(gate.state == "not started" for gate in gates)
    assert not any(gate.state == "passed" for gate in gates)


def test_paper_trades_move_the_paper_gate_to_running_not_passed(tmp_path):
    frame = journal_of([{"net": 100.0, "r": 1.0, "source": "paper"}], tmp_path)
    gates = default_gates(frame)
    assert gates[4].state == "running"
    assert "needs 100" in gates[4].detail


def test_the_table_view_is_present_for_every_chart(tmp_path):
    """Identity is never colour alone: the journal table is the table view."""
    frame = journal_of([{"net": 100.0, "r": 1.0}], tmp_path)
    page = build_page(Dashboard(journal=frame, gates=default_gates(frame)))
    assert "<table>" in page
    assert "<thead>" in page


# --- the thing a shared page must not contain -------------------------------


def test_the_page_holds_no_credential_and_cannot_reach_a_broker(tmp_path):
    """The record asks for a kill switch here. It cannot be here.

    This page is meant to be sent to people. Naming the environment variable in
    the setup steps is fine and useful; carrying a value, or any way to call a
    broker, is not.
    """
    frame = journal_of([{"net": 100.0, "r": 1.0}], tmp_path)
    page = build_page(Dashboard(journal=frame, gates=default_gates(frame)))

    # No way to reach an account.
    for host in ("api-fxpractice.oanda.com", "api-fxtrade.oanda.com",
                 "stream-fxpractice.oanda.com", "stream-fxtrade.oanda.com"):
        assert host not in page
    assert "Bearer" not in page
    assert "fetch(" not in page
    assert "XMLHttpRequest" not in page

    # The token name may appear in the instructions, but never with a value
    # after it.
    for match in re.finditer(r"OANDA_\w*TOKEN=(\S*)", page):
        assert match.group(1) in ("", "..."), match.group(0)

    # And it says where the kill switch actually is.
    assert "ict flatten" in page


def test_the_page_needs_no_network_at_all(tmp_path):
    frame = journal_of([{"net": 100.0, "r": 1.0}], tmp_path)
    page = build_page(Dashboard(journal=frame, gates=default_gates(frame)))
    assert "<script src=" not in page
    assert "http://" not in page
    # oanda.com appears once, as where to open an account. Nothing is fetched.
    fetched = [u for u in re.findall(r"https://\S+", page)
               if not u.startswith("https://oanda.com")]
    assert fetched == [], fetched


# --- theming ----------------------------------------------------------------


def test_dark_mode_is_chosen_rather_than_flipped():
    """Its own steps from the same ramps, not an automatic inversion."""
    assert set(PALETTE["light"]) == set(PALETTE["dark"])
    assert PALETTE["light"]["pos"] != PALETTE["dark"]["pos"]
    assert PALETTE["light"]["surface"] != PALETTE["dark"]["surface"]


def test_the_page_defines_dark_under_the_media_query_and_the_toggle(tmp_path):
    frame = journal_of([{"net": 100.0, "r": 1.0}], tmp_path)
    page = build_page(Dashboard(journal=frame, gates=default_gates(frame)))
    assert "prefers-color-scheme: dark" in page
    assert 'data-theme="light"' in page
    assert "--surface:" in page


def test_the_body_has_an_explicit_background(tmp_path):
    frame = journal_of([{"net": 100.0, "r": 1.0}], tmp_path)
    page = build_page(Dashboard(journal=frame, gates=default_gates(frame)))
    assert re.search(r"body\s*\{[^}]*background:\s*var\(--surface\)", page)


# --- assembling -------------------------------------------------------------


def test_build_reads_a_journal_and_finds_its_sources(tmp_path):
    book = Journal(path=tmp_path / "j.csv")
    book.append(entry(source="backtest"))
    book.append(entry(source="paper"))
    board = build(journal_path=tmp_path / "j.csv")
    assert board.sources == ["backtest", "paper"]
    assert not board.has_live


def test_build_without_a_journal_still_makes_a_page(tmp_path):
    board = build(journal_path=tmp_path / "missing.csv")
    assert board.journal.empty
    page = build_page(board)
    assert "Validation gates" in page
    assert "No trades journalled yet" in page


# --- the gates open to show what to do --------------------------------------


def test_each_gate_carries_the_commands_that_would_move_it():
    """The page should answer "what do I do next", not only "where am I"."""
    gates = default_gates(pd.DataFrame())
    for gate in gates:
        assert gate.what, gate.name
        assert gate.steps, gate.name
        assert gate.done_when, gate.name
        assert any(command for _, command in gate.steps), gate.name


def test_the_first_unfinished_gate_opens_on_load():
    """"What do I do" should need no click."""
    gates = default_gates(pd.DataFrame())
    assert [g.next_up for g in gates].count(True) == 1
    assert gates[0].next_up

    page = build_page(Dashboard(gates=gates))
    assert page.count("<details") == 6
    assert page.count("<details class=\"gate muted\" open>") == 1


def test_the_gates_use_a_native_disclosure_not_a_scripted_toggle():
    """Keyboard reachable with no ARIA, prints open, works with scripting off."""
    page = build_page(Dashboard(gates=default_gates(pd.DataFrame())))
    assert "<details" in page and "<summary" in page
    assert "addEventListener(\"click\"" not in page


def test_a_gate_with_nothing_to_say_does_not_pretend_to_expand():
    page = build_page(Dashboard(gates=[Gate("Bare gate", "passed")]))
    assert "<details" not in page
    assert "gate good flat" in page


def test_commands_are_shown_as_code_so_they_can_be_copied():
    page = build_page(Dashboard(gates=default_gates(pd.DataFrame())))
    assert "<code>ict label" in page
    assert "<code>ict verify" in page
    assert "<code>ict fetch" in page
    assert "<code>ict rank" in page
    assert "<code>ict robustness" in page
    assert "<code>ict flatten</code>" in page


def test_a_long_command_wraps_rather_than_being_clipped():
    """A clipped command is one a reader retypes wrongly."""
    page = build_page(Dashboard(gates=default_gates(pd.DataFrame())))
    assert "white-space: pre-wrap" in page
    assert "overflow-wrap: anywhere" in page


def test_no_content_carries_stray_markdown():
    """The text is HTML escaped, so a backtick renders as a backtick."""
    for gate in default_gates(pd.DataFrame()):
        for text in (gate.what, gate.done_when, gate.detail):
            assert "`" not in text, text
        for description, command in gate.steps:
            assert "`" not in description, description


def test_the_gate_bodies_survive_escaping(tmp_path):
    """A quote in the prose must not break the markup."""
    gate = Gate(
        'A "quoted" gate', "not started", what='It said <b>no</b> & meant it',
        steps=(("Run <this>", "ict thing --x 1 & 2"),), done_when="a & b",
    )
    page = build_page(Dashboard(gates=[gate]))
    assert "&lt;b&gt;no&lt;/b&gt;" in page
    assert "<b>no</b>" not in page
