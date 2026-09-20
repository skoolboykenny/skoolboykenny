"""Command line entry points for Phase 1.

    ict ingest  data/raw/*.csv --out data/eurusd_1m.parquet
    ict gaps    data/eurusd_1m.parquet
    ict plot    data/eurusd_1m.parquet --date 2024-03-14
    ict sample  data/eurusd_1m.parquet --count 20 --out verification/
    ict verify  data/eurusd_1m.parquet --labels verification/labels.csv
    ict backtest data/processed/eurusd_m1.parquet --from 2021-01-01 --to 2023-12-31
    ict demo    --out data/demo_1m.parquet
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import Analysis, analyse
from .config import MARKET_TZ
from .data.loader import find_gaps, load_csvs, read_parquet, write_parquet
from .plotting.charts import plot_analysis, write_html
from .timeframes.lookahead import TimeframeStack
from .timeframes.resample import TIMEFRAMES, resample
from .backtest import CostModel, RiskConfig, SilverBulletConfig
from .backtest import measure as measure_backtest
from .backtest import report as backtest_report
from .backtest import run as run_backtest
from .verification import (
    DEFAULT_TOLERANCE_CANDLES,
    blank_labels,
    read_labels,
    report,
    score,
)


def _day_slice(candles: pd.DataFrame, day: str) -> pd.DataFrame:
    """The candles belonging to one New York calendar day."""
    ny = candles.tz_convert(MARKET_TZ)
    start = pd.Timestamp(day, tz=MARKET_TZ)
    end = start + pd.Timedelta(days=1)
    return ny.loc[(ny.index >= start) & (ny.index < end)].tz_convert("UTC")


def cmd_ingest(args: argparse.Namespace) -> int:
    """Read vendor CSVs into a cleaned Parquet store."""
    candles, report = load_csvs(args.paths, source=args.source)
    print(report.summary())
    if candles.empty:
        print("nothing to write: every row was dropped", file=sys.stderr)
        return 1
    path = write_parquet(candles, args.out)
    print(f"wrote {path}")
    return 0


def cmd_gaps(args: argparse.Namespace) -> int:
    """Report the holes in a stored series, largest first."""
    candles = read_parquet(args.parquet, side=args.side)
    gaps = find_gaps(candles, minimum=args.minimum)
    if gaps.empty:
        print(f"no gaps longer than {args.minimum}")
        return 0
    print(f"{len(gaps)} gaps longer than {args.minimum}, largest first:\n")
    print(gaps.head(args.limit).to_string(index=False))
    return 0


def cmd_plot(args: argparse.Namespace) -> int:
    """Annotate one New York day across the timeframe stack."""
    candles = read_parquet(args.parquet, side=args.side)
    day = _day_slice(candles, args.date)
    if day.empty:
        print(f"no candles on {args.date}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    timeframes = args.timeframes or list(TIMEFRAMES)

    # Higher timeframes need context from before the day, or a 4h chart of one
    # day is six candles. Detectors run on the wider window; the view is the day.
    context = candles.loc[
        candles.index >= day.index[0] - pd.Timedelta(days=args.context_days)
    ]
    context = context.loc[context.index <= day.index[-1]]

    for timeframe in timeframes:
        frame = resample(context, timeframe)
        if timeframe == "1m":
            frame = day
        if frame.empty:
            print(f"  {timeframe}: no candles, skipped")
            continue
        analysis = analyse(frame, timeframe=timeframe, with_levels=timeframe == "1m")
        figure = plot_analysis(
            analysis, title=f"{args.date} · {timeframe} · New York time"
        )
        path = out_dir / f"{args.date}_{timeframe}.html"
        write_html(figure, str(path))
        counts = analysis.counts()
        summary = " ".join(f"{k}={v}" for k, v in counts.items() if k != "candles")
        print(f"  {timeframe}: {counts['candles']} candles · {summary} → {path}")
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    """Export random days as charts, for hand labelling against the detectors.

    The verification gate is 90% agreement with hand labels over 100 charts per
    concept. This is how those charts get produced: randomly, so the sample is
    not quietly chosen from days the detectors already handle well.
    """
    candles = read_parquet(args.parquet, side=args.side)
    days = sorted({stamp.date() for stamp in candles.tz_convert(MARKET_TZ).index})
    if not days:
        print("no candles to sample", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    chosen = rng.sample(days, min(args.count, len(days)))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Kept in a separate folder so they cannot be opened by accident while
    # labelling.
    answers_dir = out_dir / "answers"
    if args.with_answers:
        answers_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for day in sorted(chosen):
        frame = _day_slice(candles, str(day))
        if frame.empty:
            continue
        if args.timeframe != "1m":
            # The chart has to be on the timeframe it claims: a 15m label
            # scored against 1m detectors would fail for the wrong reason.
            frame = resample(frame, args.timeframe)
            if frame.empty:
                continue
        analysis = analyse(
            frame, timeframe=args.timeframe, with_levels=args.timeframe == "1m"
        )

        # The chart to label carries no detector marks. Showing someone the
        # answers and then asking them to mark the chart independently is not
        # verification: they would anchor on what is already drawn, and a
        # detector that is systematically wrong would sail through the gate it
        # exists to fail. Only the objective furniture is kept: the kill zone
        # shading and the session levels, both read off the clock rather than
        # inferred.
        clean = plot_analysis(
            analysis,
            title=f"{day} · {args.timeframe} · mark this one",
            show=("levels",),
        )
        path = out_dir / f"{day}_{args.timeframe}.html"
        write_html(clean, str(path))

        if args.with_answers:
            annotated = plot_analysis(
                analysis, title=f"{day} · {args.timeframe} · detector output"
            )
            answer_path = answers_dir / f"{day}_{args.timeframe}_annotated.html"
            write_html(annotated, str(answer_path))

        rows.append({"date": day, "chart": path.name, **analysis.counts()})

    if not rows:
        print("no days produced a chart", file=sys.stderr)
        return 1

    manifest = pd.DataFrame(rows)
    manifest_path = out_dir / "manifest.csv"
    # The detector's own counts are an answer key too, so they are written
    # where they will not be read by accident.
    if args.with_answers:
        manifest_path = answers_dir / "manifest.csv"
    manifest.to_csv(manifest_path, index=False)

    # A blank labels file, so there is an obvious place to record hand marks.
    labels_path = out_dir / "labels.csv"
    if labels_path.exists():
        print(f"kept the existing {labels_path}")
    else:
        blank_labels().to_csv(labels_path, index=False)

    print(f"wrote {len(rows)} charts to {out_dir} and a blank {labels_path.name}")
    print(
        "\nThe charts carry no detector marks, on purpose. Mark each one by"
        "\nhand into labels.csv, one row per concept you can see, then score"
        "\nthe detectors against your marks:"
        f"\n\n    ict verify {args.parquet} --labels {labels_path}\n"
    )
    if args.with_answers:
        print(
            f"The detector's own output is in {answers_dir}. Do not open it"
            "\nuntil after you have finished labelling.\n"
        )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Score hand labels against the detectors, and apply the 90% gate."""
    labels = read_labels(args.labels)
    if labels.empty:
        print(
            f"{args.labels} has no labels in it yet. Mark the charts from "
            "`ict sample` first.",
            file=sys.stderr,
        )
        return 1

    candles = read_parquet(args.parquet, side=args.side)
    wanted = {
        (str(day), str(timeframe))
        for day, timeframe in zip(labels["date"], labels["timeframe"])
    }

    analyses: dict[tuple[str, str], Analysis] = {}
    for day, timeframe in sorted(wanted):
        frame = _day_slice(candles, day)
        if frame.empty:
            print(f"warning: no candles on {day}, skipped", file=sys.stderr)
            continue
        if timeframe != "1m":
            frame = resample(frame, timeframe)
        if frame.empty:
            continue
        analyses[(day, timeframe)] = analyse(
            frame, timeframe=timeframe, with_levels=timeframe == "1m"
        )

    if not analyses:
        print("none of the labelled days are in this file", file=sys.stderr)
        return 1

    # The tolerance is in candles, so it scales with the timeframe marked.
    minutes = {"1m": 1, "15m": 15, "1h": 60, "4h": 240}
    largest = max(minutes[tf] for _, tf in analyses)
    tolerance = pd.Timedelta(minutes=largest * args.tolerance)

    scores = score(labels, analyses, tolerance)
    print(
        f"scored {len(labels)} labels over {len(analyses)} "
        f"day/timeframe combinations, tolerance {tolerance}\n"
    )
    print(report(scores))
    return 0 if all(item.passes for item in scores) else 1


def cmd_backtest(args: argparse.Namespace) -> int:
    """Run the Silver Bullet over a date range and report the result."""
    candles = read_parquet(args.parquet, side=args.side)
    if args.start:
        candles = candles.loc[candles.index >= pd.Timestamp(args.start, tz="UTC")]
    if args.end:
        candles = candles.loc[candles.index <= pd.Timestamp(args.end, tz="UTC")]
    if candles.empty:
        print("no candles in that range", file=sys.stderr)
        return 1

    result = run_backtest(
        candles,
        costs=CostModel(
            fallback_spread=args.spread,
            slippage=args.slippage,
            commission=args.commission,
        ),
        risk=RiskConfig(risk_per_trade=args.risk),
        strategy_config=SilverBulletConfig(
            minimum_r=args.minimum_r,
            draw_timeframe=args.draw_timeframe,
            order_life_minutes=args.order_life,
        ),
        starting_equity=args.equity,
    )
    metrics = measure_backtest(result)
    print(
        backtest_report(
            result,
            metrics,
            combinations_tried=args.combinations_tried,
            verified=args.verified,
        )
    )

    if args.journal:
        path = Path(args.journal)
        path.parent.mkdir(parents=True, exist_ok=True)
        result.to_frame().to_csv(path, index=False)
        print(f"\nwrote the trade journal to {path}")

    return 0 if metrics.passes else 1


def cmd_demo(args: argparse.Namespace) -> int:
    """Generate synthetic 1 minute candles, so the tooling runs before data lands."""
    candles = synthetic_candles(days=args.days, seed=args.seed)
    path = write_parquet(candles, args.out)
    print(f"wrote {len(candles):,} synthetic 1 minute candles to {path}")
    print("Synthetic data is for exercising the pipeline only, never for results.")
    return 0


def synthetic_candles(days: int = 5, seed: int = 7) -> pd.DataFrame:
    """A random walk shaped like EUR/USD, with the weekend removed."""
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2024-03-04 00:00", tz=MARKET_TZ).tz_convert("UTC")
    index = pd.date_range(start, periods=days * 24 * 60, freq="1min", tz="UTC")
    index = index[index.dayofweek < 5]

    steps = rng.normal(0, 0.00012, len(index))
    closes = 1.0850 + np.cumsum(steps)
    opens = np.concatenate([[1.0850], closes[:-1]])
    spread = np.abs(rng.normal(0, 0.00009, len(index)))
    highs = np.maximum(opens, closes) + spread
    lows = np.minimum(opens, closes) - spread

    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": rng.integers(10, 400, len(index)).astype(float),
        },
        index=index.rename("timestamp"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ict", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="read vendor CSVs into a Parquet store")
    ingest.add_argument("paths", nargs="+")
    ingest.add_argument("--source", default="histdata", choices=["histdata", "dukascopy"])
    ingest.add_argument("--out", required=True)
    ingest.set_defaults(func=cmd_ingest)

    gaps = sub.add_parser("gaps", help="report gaps in a stored series")
    gaps.add_argument("parquet")
    gaps.add_argument("--minimum", default="10min")
    gaps.add_argument("--limit", type=int, default=25)
    gaps.add_argument("--side", default="mid", choices=["mid", "bid", "ask"])
    gaps.set_defaults(func=cmd_gaps)

    plot = sub.add_parser("plot", help="annotate one day across the timeframe stack")
    plot.add_argument("parquet")
    plot.add_argument("--date", required=True, help="New York calendar date, YYYY-MM-DD")
    plot.add_argument("--timeframes", nargs="*", choices=list(TIMEFRAMES))
    plot.add_argument("--context-days", type=int, default=10)
    plot.add_argument("--out", default="charts")
    plot.add_argument("--side", default="mid", choices=["mid", "bid", "ask"])
    plot.set_defaults(func=cmd_plot)

    sample = sub.add_parser("sample", help="export random charts for hand labelling")
    sample.add_argument("parquet")
    sample.add_argument("--count", type=int, default=20)
    sample.add_argument("--timeframe", default="15m", choices=list(TIMEFRAMES))
    sample.add_argument("--seed", type=int, default=1)
    sample.add_argument("--out", default="verification")
    sample.add_argument("--side", default="mid", choices=["mid", "bid", "ask"])
    sample.add_argument(
        "--with-answers",
        action="store_true",
        help="also write annotated charts, to review after labelling",
    )
    sample.set_defaults(func=cmd_sample)

    verify = sub.add_parser(
        "verify", help="score hand labels against the detectors"
    )
    verify.add_argument("parquet")
    verify.add_argument("--labels", required=True)
    verify.add_argument(
        "--tolerance",
        type=int,
        default=DEFAULT_TOLERANCE_CANDLES,
        help="how many candles apart a label and a detection may sit",
    )
    verify.add_argument("--side", default="mid", choices=["mid", "bid", "ask"])
    verify.set_defaults(func=cmd_verify)

    backtest = sub.add_parser(
        "backtest", help="run the Silver Bullet over a date range"
    )
    backtest.add_argument("parquet")
    backtest.add_argument("--from", dest="start", default=None)
    backtest.add_argument("--to", dest="end", default=None)
    backtest.add_argument("--equity", type=float, default=10_000.0)
    backtest.add_argument("--risk", type=float, default=0.005)
    backtest.add_argument("--minimum-r", type=float, default=2.0)
    backtest.add_argument("--order-life", type=int, default=20)
    backtest.add_argument(
        "--draw-timeframe", default="1h", choices=["15m", "1h", "4h"]
    )
    backtest.add_argument("--spread", type=float, default=0.00012)
    backtest.add_argument("--slippage", type=float, default=0.00002)
    backtest.add_argument("--commission", type=float, default=0.0)
    backtest.add_argument("--journal", default=None, help="write trades to CSV")
    backtest.add_argument(
        "--combinations-tried",
        type=int,
        default=1,
        help="how many parameter sets you have tried, for the report to state",
    )
    backtest.add_argument(
        "--verified",
        action="store_true",
        help="assert the detectors have passed `ict verify`",
    )
    backtest.add_argument("--side", default="mid", choices=["mid", "bid", "ask"])
    backtest.set_defaults(func=cmd_backtest)

    demo = sub.add_parser("demo", help="generate synthetic candles to exercise the tools")
    demo.add_argument("--days", type=int, default=5)
    demo.add_argument("--seed", type=int, default=7)
    demo.add_argument("--out", default="data/demo_1m.parquet")
    demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "build_parser", "synthetic_candles", "TimeframeStack"]
