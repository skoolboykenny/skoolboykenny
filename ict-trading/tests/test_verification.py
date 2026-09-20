"""Tests for reading processed data and scoring hand labels.

These cover the two seams that join the data step to the detectors and the
detectors to the 90% gate: reading a file built by `build_parquet.py`, and
turning hand marks into a score somebody can act on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ict.analysis import analyse
from ict.cli import main, synthetic_candles
from ict.data.loader import read_parquet, write_parquet
from ict.verification import (
    PASS_THRESHOLD,
    ConceptScore,
    blank_labels,
    read_labels,
    report,
    score_concept,
)


def processed_frame(periods: int = 200) -> pd.DataFrame:
    """A frame shaped exactly like scripts/build_parquet.py writes."""
    index = pd.date_range(
        "2024-03-04 09:00", periods=periods, freq="1min", tz="UTC", name="timestamp_utc"
    )
    walk = 1.0850 + np.cumsum(
        np.random.default_rng(5).normal(0, 0.00012, periods)
    )
    columns = {}
    for side, offset in (("bid", -0.00005), ("ask", 0.00005), ("mid", 0.0)):
        columns[f"{side}_open"] = walk + offset
        columns[f"{side}_high"] = walk + offset + 0.0003
        columns[f"{side}_low"] = walk + offset - 0.0003
        columns[f"{side}_close"] = walk + offset
    columns["spread"] = 0.0001
    columns["volume"] = 120.0
    return pd.DataFrame(columns, index=index)


# --- reading processed data -------------------------------------------------


def test_processed_file_is_readable_by_the_detectors(tmp_path):
    path = tmp_path / "eurusd_m1.parquet"
    processed_frame().to_parquet(path)

    candles = read_parquet(path)

    assert list(candles.columns)[:5] == ["open", "high", "low", "close", "volume"]
    assert str(candles.index.tz) == "UTC"
    # The detectors must run on it without any further massaging.
    assert analyse(candles, "1m").counts()["candles"] == 200


def test_side_selects_which_price_becomes_ohlc(tmp_path):
    path = tmp_path / "eurusd_m1.parquet"
    frame = processed_frame()
    frame.to_parquet(path)

    bid = read_parquet(path, side="bid")
    ask = read_parquet(path, side="ask")
    mid = read_parquet(path, side="mid")

    assert bid["close"].iloc[0] == pytest.approx(frame["bid_close"].iloc[0])
    assert ask["close"].iloc[0] == pytest.approx(frame["ask_close"].iloc[0])
    assert mid["close"].iloc[0] == pytest.approx(frame["mid_close"].iloc[0])
    assert bid["close"].iloc[0] < ask["close"].iloc[0]


def test_spread_is_carried_through_not_dropped(tmp_path):
    path = tmp_path / "eurusd_m1.parquet"
    processed_frame().to_parquet(path)

    candles = read_parquet(path)
    assert "spread" in candles.columns
    assert candles["spread"].iloc[0] == pytest.approx(0.0001)


def test_a_plain_candle_file_still_reads_unchanged(tmp_path):
    path = tmp_path / "plain.parquet"
    original = synthetic_candles(days=1)
    write_parquet(original, path)

    restored = read_parquet(path)
    assert list(restored.columns) == ["open", "high", "low", "close", "volume"]
    assert len(restored) == len(original)


def test_an_unrecognisable_file_says_so_clearly(tmp_path):
    path = tmp_path / "wrong.parquet"
    pd.DataFrame(
        {"price": [1.0, 2.0]},
        index=pd.date_range("2024-03-04", periods=2, freq="1min", tz="UTC"),
    ).to_parquet(path)

    with pytest.raises(ValueError, match="neither"):
        read_parquet(path)


def test_an_unknown_side_is_rejected(tmp_path):
    path = tmp_path / "eurusd_m1.parquet"
    processed_frame().to_parquet(path)
    with pytest.raises(ValueError, match="side must be one of"):
        read_parquet(path, side="last")


# --- scoring ----------------------------------------------------------------


def stamps(*values: str) -> pd.Series:
    return pd.Series(
        [pd.Timestamp(v, tz="UTC") for v in values], dtype="datetime64[ns, UTC]"
    )


def test_a_perfect_detector_scores_one():
    result = score_concept(
        "fvg",
        stamps("2024-03-04 09:00", "2024-03-04 10:00"),
        stamps("2024-03-04 09:00", "2024-03-04 10:00"),
        pd.Timedelta(minutes=2),
    )
    assert result.matched == 2
    assert result.recall == 1.0
    assert result.precision == 1.0
    assert result.agreement == 1.0
    assert result.passes


def test_a_detection_within_tolerance_still_matches():
    result = score_concept(
        "sweep",
        stamps("2024-03-04 09:00"),
        stamps("2024-03-04 09:02"),
        pd.Timedelta(minutes=2),
    )
    assert result.matched == 1


def test_a_detection_outside_tolerance_does_not_match():
    result = score_concept(
        "sweep",
        stamps("2024-03-04 09:00"),
        stamps("2024-03-04 09:05"),
        pd.Timedelta(minutes=2),
    )
    assert result.matched == 0
    assert result.recall == 0.0
    assert result.precision == 0.0


def test_a_missed_label_lowers_recall_only():
    result = score_concept(
        "mss",
        stamps("2024-03-04 09:00", "2024-03-04 11:00"),
        stamps("2024-03-04 09:00"),
        pd.Timedelta(minutes=2),
    )
    assert result.recall == 0.5
    assert result.precision == 1.0
    assert result.agreement == pytest.approx(0.5)


def test_an_invented_detection_lowers_precision_only():
    result = score_concept(
        "mss",
        stamps("2024-03-04 09:00"),
        stamps("2024-03-04 09:00", "2024-03-04 11:00"),
        pd.Timedelta(minutes=2),
    )
    assert result.recall == 1.0
    assert result.precision == 0.5
    assert result.agreement == pytest.approx(0.5)


def test_one_label_cannot_absorb_a_cluster_of_detections():
    # A detector firing five times around one marked event is four false
    # positives, not five matches.
    result = score_concept(
        "swing_high",
        stamps("2024-03-04 09:00"),
        stamps(
            "2024-03-04 09:00",
            "2024-03-04 09:01",
            "2024-03-04 09:02",
            "2024-03-04 09:03",
            "2024-03-04 09:04",
        ),
        pd.Timedelta(minutes=5),
    )
    assert result.matched == 1
    assert result.precision == pytest.approx(0.2)


def test_the_gate_is_ninety_percent_on_the_combined_score():
    assert PASS_THRESHOLD == 0.90

    # Perfect on both sides passes.
    assert ConceptScore("fvg", 10, 10, 10).passes

    # 10 marked, 10 found, 9 matched is one miss AND one invention, so the
    # combined score is 9 / 11 = 0.82 even though recall and precision are
    # both 0.90. The gate is deliberately stricter than either alone.
    nearly = ConceptScore("fvg", 10, 10, 9)
    assert nearly.recall == pytest.approx(0.9)
    assert nearly.precision == pytest.approx(0.9)
    assert nearly.agreement == pytest.approx(9 / 11)
    assert not nearly.passes

    # To clear it, both sides have to be near perfect: 19 of 20 each way.
    assert ConceptScore("fvg", 20, 20, 19).agreement == pytest.approx(19 / 21)
    assert ConceptScore("fvg", 100, 100, 99).passes


def test_empty_labels_do_not_crash_the_score():
    result = score_concept("fvg", stamps(), stamps(), pd.Timedelta(minutes=2))
    assert result.matched == 0
    assert result.agreement != result.agreement  # nan
    assert not result.passes


# --- the labels file --------------------------------------------------------


def test_blank_labels_has_the_documented_columns():
    assert list(blank_labels().columns) == [
        "date",
        "timeframe",
        "concept",
        "time",
        "note",
    ]


def test_labels_are_read_as_new_york_time(tmp_path):
    path = tmp_path / "labels.csv"
    path.write_text(
        "date,timeframe,concept,time,note\n"
        "2024-03-14,15m,sweep,2024-03-14 09:30,london sweep\n"
    )
    labels = read_labels(path)

    # 09:30 New York in March is 13:30 UTC.
    assert labels["time_utc"].iloc[0] == pd.Timestamp("2024-03-14 13:30", tz="UTC")


def test_an_unknown_concept_is_rejected(tmp_path):
    path = tmp_path / "labels.csv"
    path.write_text(
        "date,timeframe,concept,time,note\n2024-03-14,15m,unicorn,2024-03-14 09:30,\n"
    )
    with pytest.raises(ValueError, match="unknown concepts"):
        read_labels(path)


def test_blank_rows_are_ignored(tmp_path):
    path = tmp_path / "labels.csv"
    path.write_text(
        "date,timeframe,concept,time,note\n"
        "2024-03-14,15m,sweep,2024-03-14 09:30,\n"
        ",,,,\n"
    )
    assert len(read_labels(path)) == 1


def test_report_names_the_failing_concepts():
    text = report(
        [ConceptScore("fvg", 10, 10, 10), ConceptScore("sweep", 10, 10, 5)]
    )
    assert "sweep" in text
    assert "FAIL" in text
    assert "not ready to build a backtest on" in text


# --- end to end -------------------------------------------------------------


def test_sample_then_verify_round_trip(tmp_path):
    parquet = tmp_path / "demo.parquet"
    assert main(["demo", "--days", "3", "--out", str(parquet)]) == 0

    out = tmp_path / "verification"
    assert main(["sample", str(parquet), "--count", "1", "--out", str(out)]) == 0

    labels = out / "labels.csv"
    assert labels.exists()
    # Written blank, so verify should refuse rather than report a fake score.
    assert main(["verify", str(parquet), "--labels", str(labels)]) == 1


def test_verify_scores_labels_taken_from_the_detectors(tmp_path):
    """Labels copied from the detector's own output must score 1.0.

    This is the harness checking itself: if feeding a detector its own answers
    back does not score perfectly, the scoring is wrong, not the detector.
    """
    parquet = tmp_path / "demo.parquet"
    main(["demo", "--days", "2", "--out", str(parquet)])

    candles = read_parquet(parquet)
    day = "2024-03-04"
    from ict.cli import _day_slice
    from ict.timeframes.resample import resample

    frame = resample(_day_slice(candles, day), "15m")
    analysis = analyse(frame, timeframe="15m")
    sweeps = analysis.sweeps.head(5)
    assert not sweeps.empty, "the fixture needs a day with sweeps in it"

    rows = [
        {
            "date": day,
            "timeframe": "15m",
            "concept": "sweep",
            "time": pd.Timestamp(t).tz_convert("America/New_York").strftime(
                "%Y-%m-%d %H:%M"
            ),
            "note": "",
        }
        for t in sweeps["time"]
    ]
    labels_path = tmp_path / "labels.csv"
    pd.DataFrame(rows).to_csv(labels_path, index=False)

    from ict.verification import read_labels as _read, score as _score

    labels = _read(labels_path)
    scores = _score(
        labels, {(day, "15m"): analysis}, pd.Timedelta(minutes=30)
    )
    sweep = next(s for s in scores if s.concept == "sweep")

    assert sweep.recall == 1.0
    assert sweep.matched == len(rows)


def test_sample_charts_are_on_the_timeframe_they_claim(tmp_path):
    """A 15m sample must contain 15m candles, not 1m ones relabelled.

    Labelling a chart that says 15m but holds 1m candles, then scoring it
    against 15m detectors, would fail for a reason that has nothing to do
    with the detectors.
    """
    parquet = tmp_path / "demo.parquet"
    main(["demo", "--days", "3", "--out", str(parquet)])

    out = tmp_path / "verification"
    main(
        [
            "sample",
            str(parquet),
            "--count",
            "1",
            "--timeframe",
            "15m",
            "--out",
            str(out),
        ]
    )

    manifest = pd.read_csv(out / "manifest.csv")
    # A full trading day is 1440 one minute candles, or 96 fifteen minute ones.
    assert manifest["candles"].iloc[0] <= 96


def test_charts_for_labelling_carry_no_detector_marks(tmp_path):
    """The chart you label must not show you the answers.

    Anchoring is the failure mode: shown the detector's marks, a labeller
    agrees with them, the gate reports high agreement, and a systematically
    wrong detector passes the check built to catch it.
    """
    parquet = tmp_path / "demo.parquet"
    main(["demo", "--days", "3", "--out", str(parquet)])

    out = tmp_path / "verification"
    main(["sample", str(parquet), "--count", "1", "--out", str(out)])

    chart = next(out.glob("*.html"))
    body = chart.read_text()

    for mark in ("swing high", "swing low", "liquidity pool", "sweep", "MSS"):
        assert mark not in body, f"the labelling chart is showing {mark}"


def test_answers_are_written_separately_when_asked_for(tmp_path):
    parquet = tmp_path / "demo.parquet"
    main(["demo", "--days", "3", "--out", str(parquet)])

    out = tmp_path / "verification"
    main(
        [
            "sample",
            str(parquet),
            "--count",
            "1",
            "--out",
            str(out),
            "--with-answers",
        ]
    )

    answers = out / "answers"
    assert answers.is_dir()
    annotated = next(answers.glob("*_annotated.html"))
    assert "liquidity pool" in annotated.read_text()

    # The detector's counts are an answer key, so they live there too.
    assert (answers / "manifest.csv").exists()
    assert not (out / "manifest.csv").exists()
