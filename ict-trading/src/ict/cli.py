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

from dataclasses import replace
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
from .backtest import MODELS, CostModel, ModelConfig, RiskConfig
from .backtest import grid as parameter_grid
from .backtest import rank as rank_models
from .backtest import walk_forward
from .backtest import walk_forward_report
from .backtest.strategy import build_context
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


def cmd_fetch(args: argparse.Namespace) -> int:
    """Download candles from OANDA into the Parquet store."""
    from .data.oanda import OandaClient, OandaError, combine, download

    try:
        client = OandaClient()
    except OandaError as error:
        print(error, file=sys.stderr)
        return 2

    start = pd.Timestamp(args.start, tz="UTC")
    end = (
        pd.Timestamp(args.end, tz="UTC")
        if args.end
        else pd.Timestamp.now(tz="UTC").floor("min")
    )
    if end <= start:
        print("--end must be after --start", file=sys.stderr)
        return 1

    chunks = Path(args.chunks or Path(args.out).parent / "chunks")
    print(
        f"{args.instrument} {args.granularity} from {start:%Y-%m-%d} to "
        f"{end:%Y-%m-%d}, {client.credentials.environment} environment"
    )
    if client.credentials.is_live:
        print("Using the LIVE host. Downloading is read only, but check the token.")

    def progress(path: Path, rows: int | None) -> None:
        if rows is None:
            print(f"  {path.name}: already downloaded")
        elif rows == 0:
            print(f"  {path.name}: no candles in range")
        else:
            print(f"  {path.name}: {rows:,} candles")

    try:
        paths = download(
            args.instrument, start, end, chunks,
            client=client, granularity=args.granularity, on_progress=progress,
        )
    except OandaError as error:
        print(f"\ndownload failed: {error}", file=sys.stderr)
        print("Chunks already written are kept, so rerunning resumes.", file=sys.stderr)
        return 1

    frame = combine(paths)
    if frame.empty:
        print("no candles downloaded", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, engine="pyarrow", index=True)
    print(
        f"\nwrote {len(frame):,} candles to {out}\n"
        f"  span    {frame.index[0]} to {frame.index[-1]}\n"
        f"  spread  median {frame['spread'].median():.6f}, "
        f"95th {frame['spread'].quantile(0.95):.6f}"
    )
    print("\nNext: `ict gaps` to check for holes, then `ict sample` to start labelling.")
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


def _configured_model(args: argparse.Namespace):
    """Build the chosen model, keeping its own window defaults.

    Each model knows which sessions it trades, so the CLI overrides only what
    was asked for rather than handing it a blank config.
    """
    from dataclasses import replace

    from .backtest.strategy import build_context

    def factory(context):
        model = MODELS[args.model](context)
        model.config = replace(
            model.config,
            minimum_r=args.minimum_r,
            order_life_minutes=args.order_life,
        )
        return model

    return factory


def cmd_backtest(args: argparse.Namespace) -> int:
    """Run one ICT model over a date range and report the result."""
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
        strategy=_configured_model(args),
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


def cmd_rank(args: argparse.Namespace) -> int:
    """Walk forward every model and rank them on out of sample expectancy."""
    candles = read_parquet(args.parquet, side=args.side)
    if args.start:
        candles = candles.loc[candles.index >= pd.Timestamp(args.start, tz="UTC")]
    if args.end:
        candles = candles.loc[candles.index <= pd.Timestamp(args.end, tz="UTC")]
    if candles.empty:
        print("no candles in that range", file=sys.stderr)
        return 1

    models = args.models or sorted(MODELS)
    parameters = parameter_grid(
        minimum_r=args.minimum_r, stop_buffer=args.stop_buffer
    )
    print(
        f"{len(models)} models, {len(parameters)} parameter combinations each, "
        f"tune {args.train_days} days and test {args.test_days}\n"
    )

    # One analysis, shared by every model and every fold.
    context = build_context(candles)
    results = []
    for name in models:
        print(f"  walking {name} ...", flush=True)
        results.append(
            walk_forward(
                candles,
                model=name,
                parameters=parameters,
                train_days=args.train_days,
                test_days=args.test_days,
                context=context,
            )
        )

    table = rank_models(results)
    print()
    print(walk_forward_report(table, args.train_days, args.test_days))

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(path, index=False)
        print(f"\nwrote the ranking to {path}")
    return 0


def cmd_robustness(args: argparse.Namespace) -> int:
    """Gate 4: parameter sensitivity and Monte Carlo on one model."""
    from .backtest.robustness import monte_carlo, report as robustness_report, sensitivity

    candles = read_parquet(args.parquet, side=args.side)
    if args.start:
        candles = candles.loc[candles.index >= pd.Timestamp(args.start, tz="UTC")]
    if args.end:
        candles = candles.loc[candles.index <= pd.Timestamp(args.end, tz="UTC")]
    if candles.empty:
        print("no candles in that range", file=sys.stderr)
        return 1

    context = build_context(candles)
    # Start from the model's own defaults, which carry its windows and any
    # settings particular to it, then apply the overrides given here.
    baseline = replace(
        MODELS[args.model](context).config,
        minimum_r=args.minimum_r,
        stop_buffer=args.stop_buffer,
        order_life_minutes=args.order_life,
    )

    sense = sensitivity(
        candles, model=args.model, baseline=baseline, context=context
    )
    result = run_backtest(
        candles, strategy=args.model, strategy_config=baseline, context=context
    )
    carlo = monte_carlo(
        result.trades, samples=args.samples, ruin_threshold=args.ruin_threshold
    )

    print(robustness_report(sense, carlo, args.model))
    if not args.verified:
        print(
            "\nThe detectors have not passed the 90% gate and this may not be "
            "real data.\nRobustness of an unverified result is robustness of a bug."
        )
    # Both tests must pass for the gate to pass.
    return 0 if (sense.passes() and carlo.passes()) else 1


def cmd_live(args: argparse.Namespace) -> int:
    """Paper or live trade one model. Dry run unless --execute is passed."""
    import logging

    from .data.oanda import OandaClient, OandaError
    from .live import Guards, LiveBroker, LiveRunner

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )

    try:
        client = OandaClient()
    except OandaError as error:
        print(error, file=sys.stderr)
        return 2

    if args.execute and client.credentials.is_live and not args.i_understand:
        print(
            "Refusing to trade the LIVE environment without --i-understand.\n"
            "The project's own gates require 3 months of paper trading first.",
            file=sys.stderr,
        )
        return 2

    history = read_parquet(args.parquet, side=args.side)
    if history.empty:
        print("the runner needs history, and that file is empty", file=sys.stderr)
        return 1
    history = history.tail(args.history_candles)

    broker = LiveBroker(client, args.instrument)
    runner = LiveRunner(
        broker=broker,
        history=history,
        model=args.model,
        overrides={"minimum_r": args.minimum_r} if args.minimum_r else None,
        risk=RiskConfig(risk_per_trade=args.risk_per_trade),
        guards=Guards(
            max_drawdown=args.max_drawdown,
            max_consecutive_losses=args.max_consecutive_losses,
        ),
        dry_run=not args.execute,
    )

    if not args.execute:
        print("DRY RUN: setups are logged, nothing is sent. Pass --execute to trade.")
    print(
        f"history {len(history):,} candles to {history.index[-1]}\n"
        f"model {args.model}, {client.credentials.environment} environment\n"
        f"halt at {args.max_drawdown:.0%} drawdown or "
        f"{args.max_consecutive_losses} losses in a row\n"
    )

    halt = runner.run()
    if halt:
        print(f"\n{halt}", file=sys.stderr)
        print("A halt is final. Check the account by hand before restarting.",
              file=sys.stderr)
        return 1
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

    fetch = sub.add_parser(
        "fetch", help="download candles from OANDA (needs OANDA_API_TOKEN)"
    )
    fetch.add_argument("--instrument", default="EUR_USD")
    fetch.add_argument("--start", required=True, help="YYYY-MM-DD")
    fetch.add_argument("--end", default=None, help="YYYY-MM-DD, default now")
    fetch.add_argument("--granularity", default="M1", choices=["M1", "M15", "H1", "H4"])
    fetch.add_argument("--out", required=True)
    fetch.add_argument("--chunks", default=None, help="where monthly chunks go")
    fetch.set_defaults(func=cmd_fetch)

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
    backtest.add_argument(
        "--model", default="silver_bullet", choices=sorted(MODELS)
    )
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

    rank = sub.add_parser(
        "rank", help="walk forward every model and rank them out of sample"
    )
    rank.add_argument("parquet")
    rank.add_argument("--from", dest="start", default=None)
    rank.add_argument("--to", dest="end", default=None)
    rank.add_argument("--models", nargs="*", choices=sorted(MODELS), default=None)
    rank.add_argument("--train-days", type=int, default=120)
    rank.add_argument("--test-days", type=int, default=30)
    rank.add_argument("--minimum-r", type=float, nargs="*", default=[1.5, 2.0])
    rank.add_argument("--stop-buffer", type=float, nargs="*", default=[0.1, 0.25])
    rank.add_argument("--out", default=None, help="write the ranking to CSV")
    rank.add_argument("--side", default="mid", choices=["mid", "bid", "ask"])
    rank.set_defaults(func=cmd_rank)

    robust = sub.add_parser(
        "robustness", help="gate 4: parameter sensitivity and Monte Carlo"
    )
    robust.add_argument("parquet")
    robust.add_argument("--model", default="silver_bullet", choices=sorted(MODELS))
    robust.add_argument("--start", default=None)
    robust.add_argument("--end", default=None)
    robust.add_argument("--minimum-r", type=float, default=2.0)
    robust.add_argument("--stop-buffer", type=float, default=0.1)
    robust.add_argument("--order-life", type=int, default=20)
    robust.add_argument("--samples", type=int, default=2000)
    robust.add_argument("--ruin-threshold", type=float, default=0.30)
    robust.add_argument("--side", default="mid", choices=["mid", "bid", "ask"])
    robust.add_argument("--verified", action="store_true")
    robust.set_defaults(func=cmd_robustness)

    live = sub.add_parser(
        "live", help="paper or live trade one model (dry run by default)"
    )
    live.add_argument("parquet", help="history the detectors start from")
    live.add_argument("--instrument", default="EUR_USD")
    live.add_argument("--model", default="silver_bullet", choices=sorted(MODELS))
    live.add_argument("--history-candles", type=int, default=200_000)
    live.add_argument("--risk-per-trade", type=float, default=0.005)
    live.add_argument(
        "--minimum-r", type=float, default=None,
        help="override the model's minimum reward to risk",
    )
    live.add_argument("--max-drawdown", type=float, default=0.15)
    live.add_argument("--max-consecutive-losses", type=int, default=8)
    live.add_argument("--side", default="mid", choices=["mid", "bid", "ask"])
    live.add_argument(
        "--execute", action="store_true", help="actually send orders"
    )
    live.add_argument(
        "--i-understand", action="store_true",
        help="required to --execute against the live environment",
    )
    live.set_defaults(func=cmd_live)

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
