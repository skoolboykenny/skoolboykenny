# ICT Trading System — Phase 1: data and detectors

Deterministic detectors for Inner Circle Trader concepts, a New York aligned
timeframe stack, and annotated charts to check the detectors against by hand.

This is Phase 1 only. There is no strategy, no broker connection and no AI
layer here, by design: the question this phase answers is whether the concepts
can be defined precisely enough to detect at all, not whether they make money.

> This is an engineering and research project, not financial advice. Leveraged
> trading carries a high risk of loss.

The full plan, including the later phases, is in
[`docs/project-record.md`](docs/project-record.md).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Python 3.11 or newer. The only dependencies are pandas, numpy, pyarrow and
plotly.

## Getting data

The project's own data collection step downloads EURUSD and GBPUSD 1 minute
bid and ask candles from Dukascopy, from 2021 onward, and merges them into one
Parquet file per instrument with mid prices and spread. See
[`DATA.md`](DATA.md) for the source, the columns and how to rerun it:

```bash
python scripts/download_data.py --months 1   # check the feed is reachable
python scripts/download_data.py              # the full range, resumable
python scripts/build_parquet.py              # merge and report gaps
```

The readers below remain for loading a single instrument's candles from a
vendor CSV by hand.

Two vendors are supported. Neither needs an account for 1 minute history.

**HistData** (the quickest start). Download "ASCII M1 bars" per month from
`histdata.com` for EURUSD, unzip, then:

```bash
ict ingest data/raw/DAT_ASCII_EURUSD_M1_*.csv --source histdata \
    --out data/eurusd_1m.parquet
```

**Dukascopy**, exported as CSV with a `time,open,high,low,close,volume` header:

```bash
ict ingest data/raw/eurusd.csv --source dukascopy --out data/eurusd_1m.parquet
```

Ingest prints what it had to clean: duplicate timestamps, impossible OHLC rows,
and the flat zero-volume bars vendors pad the weekend with. Gaps are left as
gaps, never filled — a missing minute is information, and inventing candles
would give the detectors structure that never traded.

Check what the gaps are before trusting a run:

```bash
ict gaps data/eurusd_1m.parquet --minimum 1h
```

Weekend closes should dominate that list. Anything else large is a data problem.

**No data yet?** Generate synthetic candles to exercise the tooling:

```bash
ict demo --days 8 --out data/demo_1m.parquet
```

Synthetic data is for checking the pipeline runs. It is a random walk, so any
"results" from it are noise.

## Plotting a day

```bash
ict plot data/processed/eurusd_m1.parquet --date 2024-03-14 --out charts
```

Files from the data step carry bid, ask and mid prices side by side. The
detectors run on the mid price by default; `--side bid` or `--side ask` reads
the other two. The spread is carried along rather than dropped, because a
backtest that fills at the mid and ignores it will look better than the broker
will.

Writes one standalone HTML chart per timeframe (4h, 1h, 15m, 1m), each with
swings, liquidity pools, sweeps, market structure shifts, fair value gaps,
order blocks and session levels drawn on, and the kill zones shaded behind.
Everything is on a New York time axis.

Higher timeframes pull in ten days of context by default (`--context-days`), or
a 4h chart of one day would be six candles.

## Verifying the detectors

This is the gate that decides whether any of the rest is worth building on:
90% agreement with hand labels, per concept. It is manual on purpose. Nothing
here can tell you whether a detector sees what you see.

**1. Export a random sample.**

```bash
ict sample data/processed/eurusd_m1.parquet --count 100 --timeframe 15m \
    --out verification
```

Days are chosen at random rather than picked, so the sample is not quietly
drawn from days the detectors already handle. It writes one chart per day,
`manifest.csv` with the detector's own counts, and a blank `labels.csv`.

**2. Mark the charts by hand.** One row per concept you can see, into
`labels.csv`. Times are New York wall clock, matching the chart axis:

```csv
date,timeframe,concept,time,note
2024-03-14,15m,sweep,2024-03-14 09:32,took Asian low
2024-03-14,15m,mss,2024-03-14 09:47,
2024-03-14,15m,fvg,2024-03-14 09:51,entry gap
```

Concepts: `swing_high`, `swing_low`, `sweep`, `mss`, `fvg`, `order_block`.

**3. Score them.**

```bash
ict verify data/processed/eurusd_m1.parquet --labels verification/labels.csv
```

```
concept        labelled detected  matched   recall  precision  agreement  gate
----------------------------------------------------------------------------
sweep                10       11        8     0.80       0.73       0.62  FAIL

1 of 1 concepts below the 90% gate: sweep
Those detectors are not ready to build a backtest on.
```

It exits non-zero while anything is below the gate, so it can sit in CI later.

**Recall** is how much of what you marked the detector found. **Precision** is
how much of what it found you marked. Low precision is the more dangerous
failure: invented structure becomes trades.

**Agreement** is matched over everything either side claimed, and it is what
the gate reads. It is deliberately stricter than either number alone: ten marks
against ten detections with nine matched is one miss *and* one invention, so
recall and precision are both 0.90 while agreement is 9/11 = 0.82 and the gate
fails. Clearing 90% means being near perfect both ways.

A label matches a detection within a few candles either side (`--tolerance`,
default 2), because reading a timestamp off a chart by eye is approximate.

## What is implemented

| Concept | Definition in code |
| --- | --- |
| Swing high / low | High (low) strictly beyond the `n` candles either side, `n = 2` |
| Liquidity pool | Unswept swing; swings within a tolerance of ATR cluster as equal highs/lows |
| Liquidity sweep | Wick beyond a pool, close back inside within `K` candles |
| Break of structure | Close beyond the last confirmed swing, in the trend direction |
| Market structure shift | After a sweep, a displaced close beyond the last opposing swing |
| Displacement | Body at least `X` times prior ATR(14) **and** most of the candle's range |
| Fair value gap | Candle 1 high below candle 3 low (inverse for bearish), with mitigation and inversion tracked |
| Order block | Last opposing candle before a displacement leg that breaks structure, with its 50% mean threshold |
| Session levels | Asian high/low, previous day and week high/low, midnight open |

Every threshold lives in `src/ict/config.py`. There are no magic numbers in
detector code, so a later phase can sweep parameters by building a modified
`Config`.

## The two rules that make the results honest

**Nothing is known before it happened.** A swing is not confirmed until the `n`
candles on its right have closed, so `find_swings` records `confirmed_at`
separately from `time`. Pools, levels and gaps all carry the same distinction.
Filtering on it is not optional.

**No timeframe may read a candle that has not closed.** A 4h bias taken from a
4h candle still forming is a bias taken from the future, and it is the main
reason ICT backtests look better than they are. Higher timeframe data is read
through `TimeframeStack`, which has no accessor that returns a whole frame:

```python
from ict.timeframes.lookahead import TimeframeStack

stack = TimeframeStack.from_minutes(candles)
frames = stack.snapshot(now)   # every timeframe, nothing unclosed
bias_candles = stack.as_of(now, "4h")
```

## Layout

```
src/ict/
  config.py          every tunable number
  analysis.py        runs the detectors in dependency order
  cli.py             ingest · gaps · plot · sample · demo
  data/              vendor CSV readers, cleaning, Parquet store
  timeframes/        New York sessions, resampling, the lookahead guard
  detectors/         one module per concept, each a pure function
  plotting/          annotated charts
tests/               hand-built candle sequences with known answers
```

Detectors return a DataFrame of timestamped events or zones and hold no state,
so they compose: `analysis.py` threads swings into pools into sweeps into
shifts rather than recomputing them.

## Performance

Detection is roughly linear in candle count: about 3 seconds for a month of 1
minute data, so the three year backtest window of the next phase is a batch job
of a couple of minutes, not hours. The crossing queries every detector depends
on ("when did price first trade beyond this level?") go through a segment tree
in `detectors/_scan.py` rather than rescanning the frame per level.

## Phase 1 is done when

- `pytest` passes.
- `ict plot` annotates any chosen day across 1m, 15m, 1h and 4h.
- The detectors have been checked against 100 hand-marked charts per concept
  and agree at least 90% of the time.

The first two are done. The third needs hand labelling, which no amount of code
can do for you — that is the point of it.
