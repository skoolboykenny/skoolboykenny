"""End to end: synthetic data through ingest, analysis, plotting and the CLI."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ict.analysis import analyse, analyse_stack
from ict.cli import main, synthetic_candles
from ict.plotting.charts import plot_analysis
from ict.timeframes.lookahead import TimeframeStack
from ict.timeframes.resample import build_stack, timeframe_delta


def test_analysis_runs_over_every_timeframe():
    candles = synthetic_candles(days=3)
    results = analyse_stack(build_stack(candles))

    assert set(results) == {"1m", "15m", "1h", "4h"}
    for timeframe, analysis in results.items():
        counts = analysis.counts()
        assert counts["candles"] > 0, timeframe
        # A random walk should still throw up swings on every timeframe.
        assert counts["swings"] > 0, timeframe


def test_analysis_only_reports_events_inside_the_data():
    candles = synthetic_candles(days=3)
    analysis = analyse(candles, timeframe="1m")
    first, last = candles.index[0], candles.index[-1]

    for name in ("swings", "sweeps", "displacements", "breaks", "shifts", "fvgs"):
        frame = getattr(analysis, name)
        if frame.empty:
            continue
        assert frame["time"].min() >= first, name
        assert frame["time"].max() <= last, name


def test_stack_never_returns_an_unclosed_candle():
    stack = TimeframeStack.from_minutes(synthetic_candles(days=3))
    candles = stack.frames["1m"]

    # Walk a sample of minutes and check every frame at each one.
    for now in candles.index[::311]:
        for timeframe, frame in stack.snapshot(now).items():
            if frame.empty:
                continue
            assert frame.index[-1] + timeframe_delta(timeframe) <= now


def test_plot_builds_a_figure_with_candles_on_it():
    candles = synthetic_candles(days=2)
    day = candles.loc[candles.index < candles.index[0] + pd.Timedelta(days=1)]
    figure = plot_analysis(analyse(day, timeframe="1m", with_levels=True))

    kinds = [trace.type for trace in figure.data]
    assert "candlestick" in kinds


def test_cli_demo_then_plot(tmp_path: Path, capsys):
    parquet = tmp_path / "demo.parquet"
    assert main(["demo", "--days", "3", "--out", str(parquet)]) == 0
    assert parquet.exists()

    charts = tmp_path / "charts"
    assert (
        main(
            [
                "plot",
                str(parquet),
                "--date",
                "2024-03-04",
                "--timeframes",
                "15m",
                "--out",
                str(charts),
            ]
        )
        == 0
    )
    assert (charts / "2024-03-04_15m.html").exists()


def test_cli_sample_writes_a_manifest(tmp_path: Path):
    parquet = tmp_path / "demo.parquet"
    main(["demo", "--days", "4", "--out", str(parquet)])

    out = tmp_path / "verification"
    assert main(["sample", str(parquet), "--count", "2", "--out", str(out)]) == 0

    manifest = out / "manifest.csv"
    assert manifest.exists()
    rows = pd.read_csv(manifest)
    assert len(rows) == 2
    assert "swings" in rows.columns


def test_cli_gaps_reports_the_weekend(tmp_path: Path, capsys):
    parquet = tmp_path / "demo.parquet"
    main(["demo", "--days", "9", "--out", str(parquet)])

    assert main(["gaps", str(parquet), "--minimum", "1h"]) == 0
    out = capsys.readouterr().out
    assert "gaps longer than" in out


def test_plot_rejects_a_date_with_no_candles(tmp_path: Path):
    parquet = tmp_path / "demo.parquet"
    main(["demo", "--days", "2", "--out", str(parquet)])

    assert main(["plot", str(parquet), "--date", "1999-01-01", "--out", str(tmp_path)]) == 1
