"""Tests for the unattended runner.

Most of these are about what `advance` refuses to do. An agent running this on
a schedule with nobody watching is exactly the setup where "make the gate
green" quietly replaces "find out the truth", so the boundaries are tested
harder than the happy path.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ict.advance import (
    ALLOWED,
    DATA,
    State,
    Step,
    inspect,
    next_step,
    record,
    report,
    run_step,
)


def state(**overrides) -> State:
    base = {"has_token": True, "has_data": True, "candles": 100_000,
            "span": "2021-01-01 to 2024-01-01"}
    base.update(overrides)
    return State(**base)


# --- what it refuses to do --------------------------------------------------


def test_it_cannot_run_anything_that_places_an_order():
    """Nothing here may reach the live loop, in either environment."""
    for forbidden in ("live", "flatten"):
        assert forbidden not in ALLOWED
        with pytest.raises(ValueError, match="refuses to run"):
            run_step(Step("x", "x", command=[forbidden]))


def test_the_allow_list_holds_only_read_and_compute_commands():
    assert set(ALLOWED) == {
        "fetch", "gaps", "verify", "backtest", "rank", "robustness", "dashboard"
    }


def test_a_failing_gate_is_recorded_as_failed_not_retried_differently(tmp_path):
    """The gate's own exit code is the verdict. Nothing reinterprets it."""
    step = Step("gate 2 in sample", "x", command=["backtest"])
    marker = record(step, code=1, root=tmp_path)
    assert marker.name == "gate2.failed"
    assert not (tmp_path / "results" / "gate2.passed").exists()


def test_recording_a_pass_clears_an_earlier_failure(tmp_path):
    step = Step("gate 2 in sample", "x", command=["backtest"])
    record(step, code=1, root=tmp_path)
    record(step, code=0, root=tmp_path)
    assert (tmp_path / "results" / "gate2.passed").exists()
    assert not (tmp_path / "results" / "gate2.failed").exists()


def test_no_step_ever_changes_a_parameter():
    """Tuning a threshold to pass a gate is fitting, and it is the single most
    dangerous thing an unattended agent could do here."""
    for current in (
        state(gate1=False),
        state(gate1=True, gate2=False),
        state(gate1=True, gate2=True, gate3=False),
        state(gate1=True, gate2=True, gate3=True, gate4=False),
    ):
        step = next_step(current)
        flags = " ".join(step.command)
        for knob in ("--minimum-r", "--stop-buffer", "--blackout-minutes",
                     "--spread", "--order-life"):
            assert knob not in flags


# --- the order of the gates -------------------------------------------------


def test_no_gate_is_skipped():
    """Each gate blocks the ones after it, in the record's order."""
    assert next_step(state(gate1=None)).name.startswith("gate 1")
    assert next_step(state(gate1=True)).name.startswith("gate 2")
    assert next_step(state(gate1=True, gate2=True)).name.startswith("gate 3")
    assert next_step(state(gate1=True, gate2=True, gate3=True)).name.startswith("gate 4")


def test_a_failed_gate_blocks_the_ones_after_it():
    """False is not True: a gate that failed is not a gate that passed."""
    step = next_step(state(gate1=False, gate2=True, gate3=True, gate4=True))
    assert step.name.startswith("gate 1")


def test_everything_passing_stops_rather_than_starting_to_trade():
    step = next_step(state(gate1=True, gate2=True, gate3=True, gate4=True))
    assert step.name == "paper trading"
    assert step.blocked_on_person
    assert step.command == []


# --- who is blocking --------------------------------------------------------


def test_no_credentials_is_blocked_on_a_person():
    step = next_step(State())
    assert step.blocked_on_person
    assert "oanda.com" in step.instructions
    assert "Never paste the token into a chat" in step.instructions


def test_credentials_but_no_data_is_mine_to_run():
    step = next_step(state(has_data=False))
    assert step.is_mine
    assert step.command[0] == "fetch"


def test_labelling_is_blocked_on_a_person_and_says_why():
    """The reason matters: an agent could mark the charts and must not."""
    step = next_step(state(gate1=None))
    assert step.blocked_on_person
    assert "cannot be delegated" in step.instructions
    assert "agree with the code by construction" in step.instructions


def test_labels_without_the_reviewed_file_is_blocked_not_scored():
    """Scoring without it hides false positives on quiet days."""
    step = next_step(state(has_labels=True, has_reviewed=False))
    assert step.blocked_on_person
    assert "reviewed.csv" in step.instructions


def test_labels_and_reviewed_together_are_scorable():
    step = next_step(state(has_labels=True, has_reviewed=True, labelled_charts=100))
    assert step.is_mine
    assert step.command[0] == "verify"
    assert "--reviewed" in step.command


# --- reading the world ------------------------------------------------------


def test_inspect_has_no_side_effects(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    inspect(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_inspect_reads_gate_markers(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "gate1.passed").write_text("x")
    (results / "gate2.failed").write_text("x")

    found = inspect(tmp_path)
    assert found.gate1 is True
    assert found.gate2 is False
    assert found.gate3 is None


def test_inspect_survives_a_corrupt_artefact(tmp_path):
    """A half written file must not crash a scheduled run."""
    (tmp_path / "labels.csv").write_text("not,a,valid\ncsv\x00\x00")
    (tmp_path / DATA).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / DATA).write_bytes(b"not parquet")

    found = inspect(tmp_path)
    assert found.has_data is False
    assert found.has_labels is False


def test_inspect_reads_the_token_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    assert inspect(tmp_path).has_token is False
    monkeypatch.setenv("OANDA_API_TOKEN", "t")
    monkeypatch.setenv("OANDA_ENVIRONMENT", "practice")
    found = inspect(tmp_path)
    assert found.has_token is True
    assert found.environment == "practice"


# --- the report -------------------------------------------------------------


def test_the_report_names_who_is_blocking():
    current = State()
    text = report(current, next_step(current))
    assert "This one needs you" in text
    assert "credentials       missing" in text


def test_the_report_shows_a_runnable_command_when_it_is_mine():
    current = state(has_data=False)
    text = report(current, next_step(current))
    assert "Runnable now: ict fetch" in text
    assert "This one needs you" not in text


def test_the_report_never_claims_a_gate_passed_without_a_marker():
    text = report(state(), next_step(state()))
    assert "PASS" not in text
