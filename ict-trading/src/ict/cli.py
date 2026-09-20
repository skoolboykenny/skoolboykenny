"""Command line entry points for Phase 1.

    ict ingest  data/raw/*.csv --out data/eurusd_1m.parquet
    ict gaps    data/eurusd_1m.parquet
    ict plot    data/eurusd_1m.parquet --date 2024-03-14
    ict sample  data/eurusd_1m.parquet --count 20 --out verification/
    ict demo    --out data/demo_1m.parquet
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import analyse
from .config import MARKET_TZ
from .data.loader import find_gaps, load_csvs, read_parquet, write_parquet
from .plotting.charts import plot_analysis, write_html
from .timeframes.lookahead import TimeframeStack
from .timeframes.resample import TIMEFRAMES, resample


def _day_slice(candles: pd.DataFrame, day: str) -> pd.DataFrame:
    """The candles belonging to one New York calendar day."""
    ny = candles.tz_convert(MARKET_TZ)
    start = pd.Timestamp(day, tz=MARKET_TZ)
    end = start + pd.Timedelta(days=1)
    return ny.loc[(ny.index >= start) & (ny.index < end)].tz_convert("UTC")


def cmd_ingest(args: argparse.Namespace) -> int:
    candles, report = load_csvs(args.paths, source=args.source)
    print(report.summary())
    if candles.empty:
        print("nothing to write: every row was dropped", file=sys.stderr)
        return 1
    path = write_parquet(candles, args.out)
    print(f"wrote {path}")
    return 0


def cmd_gaps(args: argparse.Namespace) -> int:
    candles = read_parquet(args.parquet)
    gaps = find_gaps(candles, minimum=args.minimum)
    if gaps.empty:
        print(f"no gaps longer than {args.minimum}")
        return 0
    print(f"{len(gaps)} gaps longer than {args.minimum}, largest first:\n")
    print(gaps.head(args.limit).to_string(index=False))
    return 0


def cmd_plot(args: argparse.Namespace) -> int:
    candles = read_parquet(args.parquet)
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
    candles = read_parquet(args.parquet)
    days = sorted({stamp.date() for stamp in candles.tz_convert(MARKET_TZ).index})
    if not days:
        print("no candles to sample", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    chosen = rng.sample(days, min(args.count, len(days)))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for day in sorted(chosen):
        frame = _day_slice(candles, str(day))
        if frame.empty:
            continue
        analysis = analyse(frame, timeframe=args.timeframe, with_levels=True)
        figure = plot_analysis(analysis, title=f"{day} · {args.timeframe}")
        path = out_dir / f"{day}_{args.timeframe}.html"
        write_html(figure, str(path))
        rows.append({"date": day, "chart": path.name, **analysis.counts()})

    if not rows:
        print("no days produced a chart", file=sys.stderr)
        return 1

    manifest = pd.DataFrame(rows)
    manifest_path = out_dir / "manifest.csv"
    manifest.to_csv(manifest_path, index=False)
    print(f"wrote {len(rows)} charts and {manifest_path}")
    print("\nMark each chart by hand, then compare against these counts:\n")
    print(manifest.to_string(index=False))
    return 0


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
    gaps.set_defaults(func=cmd_gaps)

    plot = sub.add_parser("plot", help="annotate one day across the timeframe stack")
    plot.add_argument("parquet")
    plot.add_argument("--date", required=True, help="New York calendar date, YYYY-MM-DD")
    plot.add_argument("--timeframes", nargs="*", choices=list(TIMEFRAMES))
    plot.add_argument("--context-days", type=int, default=10)
    plot.add_argument("--out", default="charts")
    plot.set_defaults(func=cmd_plot)

    sample = sub.add_parser("sample", help="export random charts for hand labelling")
    sample.add_argument("parquet")
    sample.add_argument("--count", type=int, default=20)
    sample.add_argument("--timeframe", default="15m", choices=list(TIMEFRAMES))
    sample.add_argument("--seed", type=int, default=1)
    sample.add_argument("--out", default="verification")
    sample.set_defaults(func=cmd_sample)

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
