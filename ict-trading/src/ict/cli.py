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


def cmd_label(args: argparse.Namespace) -> int:
    """Build the click to mark labelling page for gate 1."""
    from .labelling import build_chart, build_page

    candles = read_parquet(args.parquet, side=args.side)
    days = sorted({stamp.date() for stamp in candles.tz_convert(MARKET_TZ).index})
    if not days:
        print("no candles to sample", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    chosen = sorted(rng.sample(days, min(args.count, len(days))))

    charts = []
    for day in chosen:
        frame = _day_slice(candles, str(day))
        if frame.empty:
            continue
        if args.timeframe != "1m":
            frame = resample(frame, args.timeframe)
            if frame.empty:
                continue
        charts.append(build_chart(frame, str(day), args.timeframe))

    if not charts:
        print("no days produced a chart", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        build_page(charts, title=f"ICT labelling · {args.timeframe}"),
        encoding="utf-8",
    )

    print(f"wrote {len(charts)} charts to {out}")
    print(f"\nOpen it in a browser:\n\n    file://{out.resolve()}\n")
    print(
        "Click a candle to mark it. Keys: "
        + ", ".join(f"{key} {concept.replace('_', ' ')}"
                    for concept, key, _, _ in __import__(
                        "ict.labelling", fromlist=["MARKERS"]).MARKERS)
        + ".\n0 records a chart with nothing on it, which the gate needs."
    )
    print(
        "\nWork is saved in the browser as you go. When you are done, press"
        "\nDownload labels, then score the detectors against your marks:"
        f"\n\n    ict verify {args.parquet} --labels labels.csv "
        "--reviewed reviewed.csv\n"
    )
    if len(days) < args.count:
        print(
            f"Note: only {len(days)} days of data, fewer than the {args.count} "
            "asked for.\nThe gate wants 100 charts per concept."
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

    reviewed = None
    if args.reviewed:
        from .verification import read_reviewed

        reviewed = read_reviewed(args.reviewed)
        # A chart looked at and left blank has no labels, so it would never be
        # analysed without this. Those are exactly the charts that catch a
        # detector firing on quiet days.
        wanted |= reviewed

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

    if reviewed is None:
        blank = 0
        print(
            "No --reviewed file given. Only charts carrying at least one label\n"
            "are scored, so every detection on a chart you correctly left blank\n"
            "is invisible, and a detector that over-fires on quiet days passes.\n"
            "The labelling page writes reviewed.csv for this.\n",
            file=sys.stderr,
        )
    else:
        blank = len(reviewed) - len({k for k in wanted if k in reviewed and any(
            (str(d), str(t)) == k
            for d, t in zip(labels["date"], labels["timeframe"])
        )})
        if blank > 0:
            print(
                f"{blank} of {len(reviewed)} reviewed charts carry no labels. "
                "Their detections count as false positives.\n"
            )

    scores = score(labels, analyses, tolerance, reviewed=reviewed)
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

    from .review import Journal

    gate = _news_gate(args)
    reviewer = _reviewer(args)
    decisions = Journal() if reviewer is not None else None

    if gate is not None:
        from .news import gated_minutes

        share = gated_minutes(gate, candles.index)
        print(f"news gate: {len(gate.blackouts)} windows, {share:.1%} of candles "
              f"blocked\n")

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
        news_gate=gate,
        reviewer=reviewer,
        journal=decisions,
    )
    metrics = measure_backtest(result)
    if decisions is not None and args.review_journal:
        path = decisions.write_csv(args.review_journal)
        print(f"{len(decisions.decisions)} review decisions written to {path}\n")
    print(
        backtest_report(
            result,
            metrics,
            combinations_tried=args.combinations_tried,
            verified=args.verified,
        )
    )

    if args.journal:
        # The journal's own shape, not the raw result frame, so a backtest
        # journal and a paper one can be read by the same tooling and compared
        # column for column.
        from .journal import Journal as TradeJournal

        book = TradeJournal(
            path=args.journal, instrument=args.instrument, source="backtest"
        )
        for trade in result.trades:
            book.add(trade, model=result.parameters.get("model", ""))
        path = book.write_all()
        print(f"\nwrote the trade journal to {path}")
        print("Summarise it with `ict journal`.")

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

    from .review import Journal

    gate = _news_gate(args)
    reviewer = _reviewer(args)
    decisions = Journal() if reviewer is not None else None

    from .alerts import Alerts
    from .journal import Journal as TradeJournal

    alerts = Alerts.default(args.alert_log)
    trades = TradeJournal(
        path=args.trade_journal,
        instrument=args.instrument,
        source="live" if client.credentials.is_live else "paper",
    ) if args.trade_journal and args.execute else None

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
        news_gate=gate,
        reviewer=reviewer,
        journal=decisions,
        trade_journal=trades,
        alerts=alerts,
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

    if gate is not None:
        print(gate.summary() + "\n")
    else:
        print("No calendar loaded, so no news gate is active.\n")
    if reviewer is not None:
        print(f"review layer: {args.review}. It may only skip or shrink a trade.\n")

    if trades is not None:
        print(f"trades are journalled to {trades.path}, one row per close.\n")

    halt = runner.run()
    if decisions is not None and args.review_journal:
        path = decisions.write_csv(args.review_journal)
        print(f"\n{len(decisions.decisions)} review decisions written to {path}")
        print("Score them with `ict review-audit` once the outcomes are known.")
    if halt:
        print(f"\n{halt}", file=sys.stderr)
        print("A halt is final. Check the account by hand before restarting.",
              file=sys.stderr)
        return 1
    return 0


def _news_gate(args: argparse.Namespace):
    """Build the news gate from a calendar file, or nothing if none was given."""
    from .news import NewsGate, read_calendar

    if not getattr(args, "calendar", None):
        return None
    frame = read_calendar(
        args.calendar, timezone=args.calendar_timezone
    )
    return NewsGate(
        frame,
        instrument=getattr(args, "instrument", "EUR_USD"),
        minutes_before=args.blackout_minutes,
        minutes_after=args.blackout_minutes,
        block_fomc_day=getattr(args, "block_fomc_day", False),
    )


def _reviewer(args: argparse.Namespace):
    """Build the review layer named on the command line."""
    from .review import AlwaysTake, ClaudeReviewer, RuleReviewer

    choice = getattr(args, "review", "off")
    if choice in (None, "off"):
        return None
    if choice == "rules":
        return RuleReviewer()
    if choice == "claude":
        return ClaudeReviewer()
    return AlwaysTake()


def cmd_news(args: argparse.Namespace) -> int:
    """Show what a calendar would gate, before it gates anything."""
    from .news import NewsGate, events, read_calendar, scaled_surprise

    frame = read_calendar(args.calendar, timezone=args.calendar_timezone)
    if frame.empty:
        print("no events read from that file", file=sys.stderr)
        return 1

    print(f"{len(frame):,} events, {frame['time'].min()} to {frame['time'].max()}")
    counts = frame["impact"].value_counts()
    for level in ("high", "medium", "low"):
        print(f"  {level:<7}{int(counts.get(level, 0)):>6}")

    gate = NewsGate(
        frame,
        instrument=args.instrument,
        minutes_before=args.blackout_minutes,
        minutes_after=args.blackout_minutes,
        block_fomc_day=args.block_fomc_day,
    )
    print()
    print(gate.summary())

    if args.parquet:
        from .news import gated_minutes

        candles = read_parquet(args.parquet, side="mid")
        share = gated_minutes(gate, candles.index)
        print(f"\nthe gate blocks {share:.1%} of the {len(candles):,} candles in "
              f"{Path(args.parquet).name}")
        if share > 0.2:
            print("That is a large share. A gate this wide is a different "
                  "strategy, not a filter, and results are no longer\n"
                  "comparable with an ungated run.")

    tradeable = [e for e in events(frame) if e.actual is not None]
    if tradeable:
        surprises = scaled_surprise(frame).dropna()
        print(f"\n{len(tradeable):,} events have an actual figure; "
              f"{len(surprises):,} have enough history to scale a surprise")
    return 0


def cmd_review_audit(args: argparse.Namespace) -> int:
    """Score a decision journal and say whether the layer should stay on."""
    from .review import Journal, audit
    from .review.audit import Decision

    frame = pd.read_csv(args.journal)
    journal = Journal()
    for row in frame.itertuples():
        journal.decisions.append(
            Decision(
                at=pd.Timestamp(row.at),
                instrument=str(getattr(row, "instrument", "")),
                model=str(getattr(row, "model", "")),
                direction=str(getattr(row, "direction", "")),
                entry=float(getattr(row, "entry", 0.0) or 0.0),
                stop=float(getattr(row, "stop", 0.0) or 0.0),
                target=float(getattr(row, "target", 0.0) or 0.0),
                reward_to_risk=float(getattr(row, "reward_to_risk", 0.0) or 0.0),
                action=str(row.action),
                size_multiple=float(row.size_multiple),
                reason=str(getattr(row, "reason", "")),
                reviewer=str(getattr(row, "reviewer", "")),
                outcome_r=(
                    None if pd.isna(getattr(row, "outcome_r", None))
                    else float(row.outcome_r)
                ),
            )
        )

    result = audit(journal)
    print(result.summary())
    # Non-zero when the layer should come off, so this can gate a build.
    return 1 if (result.has_enough_evidence and result.should_switch_off) else 0


def cmd_plan(args: argparse.Namespace) -> int:
    """The daily routine: bias, path, levels, news and account state."""
    from .plan import build_plan

    candles = read_parquet(args.parquet, side=args.side)
    if candles.empty:
        print("that file has no candles", file=sys.stderr)
        return 1

    broker = None
    if args.account:
        from .data.oanda import OandaClient, OandaError
        from .live import LiveBroker

        try:
            broker = LiveBroker(OandaClient(), args.instrument)
        except OandaError as error:
            print(f"no account: {error}\n", file=sys.stderr)

    plan = build_plan(
        candles,
        instrument=args.instrument,
        now=pd.Timestamp(args.at, tz="UTC") if args.at else None,
        news_gate=_news_gate(args),
        broker=broker,
    )

    print(plan.message() if args.message_only else plan.report())

    if args.alert:
        from .alerts import Alerts

        Alerts.default(args.alert_log).info(plan.message())
    return 0


def cmd_journal(args: argparse.Namespace) -> int:
    """Summarise a trade journal."""
    from .journal import daily_breakdown, read_journal, summarise

    path = Path(args.journal)
    if not path.exists():
        print(f"no journal at {path}", file=sys.stderr)
        return 1

    frame = read_journal(path)
    since = pd.Timestamp(args.since, tz="UTC") if args.since else None
    print(summarise(frame, since=since))

    if args.daily and not frame.empty:
        print("\nBy day")
        print("-" * 66)
        for row in daily_breakdown(frame).itertuples():
            print(f"  {row.date}  {row.trades:>3} trades  "
                  f"{row.r_multiple:+7.2f}R  {row.net:+10.2f}")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Build the dashboard: gates, results, journal, in one page."""
    from .dashboard import build, build_page

    board = build(journal_path=args.journal, title=args.title)
    if board.journal.empty and not Path(args.journal).exists():
        print(
            f"no journal at {args.journal}. The page will show the gates and "
            "nothing else.",
            file=sys.stderr,
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page(board), encoding="utf-8")

    size = out.stat().st_size / 1024
    print(f"wrote {out} ({size:.0f} KB)")
    print(f"\n    file://{out.resolve()}\n")
    if not board.has_live:
        print(
            "The page says plainly that there is no live money in this record."
            "\nLeave that in. It is the reason the page is worth showing anyone."
        )
    return 0


def cmd_flatten(args: argparse.Namespace) -> int:
    """The kill switch: cancel every order and close every position.

    Not a button in the dashboard. That page is meant to be sent to people, and
    a button that closes positions would need a live trading token inside a
    shared file. Here the token is already in the environment and the
    confirmation is a person rather than a click.
    """
    from .data.oanda import OandaClient, OandaError
    from .live import LiveBroker

    try:
        client = OandaClient()
        broker = LiveBroker(client, args.instrument)
        orders = broker.pending_orders()
        trades = broker.open_trades()
    except OandaError as error:
        print(error, file=sys.stderr)
        return 2

    where = client.credentials.environment.upper()
    print(f"{where} account {client.credentials.account_id}")
    print(f"  {len(orders)} resting orders")
    print(f"  {len(trades)} open positions")
    if not orders and not trades:
        print("\nNothing to flatten.")
        return 0

    if not args.yes:
        answer = input(
            f"\nCancel {len(orders)} orders and close {len(trades)} positions "
            "at market? [y/N] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            print("Left alone.")
            return 1

    cancelled = broker.cancel_all()
    closed = broker.close_all()
    print(f"\ncancelled {cancelled} orders, closed {closed} positions")

    from .alerts import Alerts

    Alerts.default(args.alert_log).halt(
        f"flattened by hand: {cancelled} orders cancelled, "
        f"{closed} positions closed"
    )
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

    label = sub.add_parser(
        "label", help="build the click to mark labelling page (gate 1)"
    )
    label.add_argument("parquet")
    label.add_argument("--count", type=int, default=100)
    label.add_argument("--timeframe", default="15m", choices=list(TIMEFRAMES))
    label.add_argument("--seed", type=int, default=1)
    label.add_argument("--out", default="labelling.html")
    label.add_argument("--side", default="mid", choices=["mid", "bid", "ask"])
    label.set_defaults(func=cmd_label)

    verify = sub.add_parser(
        "verify", help="score hand labels against the detectors"
    )
    verify.add_argument("parquet")
    verify.add_argument("--labels", required=True)
    verify.add_argument(
        "--reviewed",
        default=None,
        help="charts you looked at, from the labelling page. Without it, "
             "false positives on charts you correctly left blank are invisible",
    )
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
    backtest.add_argument("--instrument", default="EUR_USD")
    backtest.add_argument("--calendar", default=None, help="calendar CSV, enables the news gate")
    backtest.add_argument("--calendar-timezone", default=MARKET_TZ)
    backtest.add_argument("--blackout-minutes", type=int, default=15)
    backtest.add_argument("--block-fomc-day", action="store_true")
    backtest.add_argument(
        "--review", default="off", choices=["off", "rules", "claude"],
        help="the AI review layer; it may only skip or shrink a trade",
    )
    backtest.add_argument(
        "--review-journal", default=None,
        help="write every review decision, including the skips, to CSV",
    )
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

    plan = sub.add_parser("plan", help="the daily plan: bias, path, levels, news")
    plan.add_argument("parquet")
    plan.add_argument("--instrument", default="EUR_USD")
    plan.add_argument("--at", default=None, help="plan as at this UTC moment")
    plan.add_argument("--side", default="mid", choices=["mid", "bid", "ask"])
    plan.add_argument("--calendar", default=None)
    plan.add_argument("--calendar-timezone", default=MARKET_TZ)
    plan.add_argument("--blackout-minutes", type=int, default=15)
    plan.add_argument("--block-fomc-day", action="store_true")
    plan.add_argument("--account", action="store_true", help="include broker state")
    plan.add_argument("--message-only", action="store_true", help="just the one liner")
    plan.add_argument("--alert", action="store_true", help="send the plan as an alert")
    plan.add_argument("--alert-log", default=None)
    plan.set_defaults(func=cmd_plan)

    dash = sub.add_parser(
        "dashboard", help="build the dashboard page from a journal"
    )
    dash.add_argument("--journal", default="journal.csv")
    dash.add_argument("--out", default="dashboard.html")
    dash.add_argument("--title", default="ICT trading system")
    dash.set_defaults(func=cmd_dashboard)

    flatten = sub.add_parser(
        "flatten", help="kill switch: cancel every order, close every position"
    )
    flatten.add_argument("--instrument", default="EUR_USD")
    flatten.add_argument("--yes", action="store_true", help="skip the prompt")
    flatten.add_argument("--alert-log", default=None)
    flatten.set_defaults(func=cmd_flatten)

    journal = sub.add_parser("journal", help="summarise a trade journal")
    journal.add_argument("journal")
    journal.add_argument("--since", default=None, help="only trades closed after this")
    journal.add_argument("--daily", action="store_true", help="show R per day")
    journal.set_defaults(func=cmd_journal)

    news = sub.add_parser("news", help="show what a calendar would gate")
    news.add_argument("calendar", help="calendar CSV export")
    news.add_argument("--parquet", default=None, help="score the gate against a series")
    news.add_argument("--instrument", default="EUR_USD")
    news.add_argument("--calendar-timezone", default=MARKET_TZ)
    news.add_argument("--blackout-minutes", type=int, default=15)
    news.add_argument("--block-fomc-day", action="store_true")
    news.set_defaults(func=cmd_news)

    audit_parser = sub.add_parser(
        "review-audit", help="score a review journal and say whether to keep the layer"
    )
    audit_parser.add_argument("journal", help="decisions CSV written by the journal")
    audit_parser.set_defaults(func=cmd_review_audit)

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
    live.add_argument("--calendar", default=None, help="calendar CSV, enables the news gate")
    live.add_argument("--calendar-timezone", default=MARKET_TZ)
    live.add_argument("--blackout-minutes", type=int, default=15)
    live.add_argument("--block-fomc-day", action="store_true")
    live.add_argument(
        "--review", default="off", choices=["off", "rules", "claude"],
        help="the AI review layer; it may only skip or shrink a trade",
    )
    live.add_argument(
        "--review-journal", default="review-decisions.csv",
        help="where every review decision is written, skips included",
    )
    live.add_argument(
        "--trade-journal", default="journal.csv",
        help="append every closed trade here, one row at a time",
    )
    live.add_argument("--alert-log", default=None, help="append alerts to this file")
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
