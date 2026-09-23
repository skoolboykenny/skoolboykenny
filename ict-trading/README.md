# ICT Trading System

Deterministic detectors for Inner Circle Trader concepts, a New York aligned
timeframe stack, and annotated charts to check the detectors against by hand.

Phases 1 to 3 are built: the detectors, a backtest engine, the seven ICT models
from the project record, and a walk forward that ranks them out of sample. There
is no broker connection and no AI layer yet.

The question these phases answer is whether the concepts can be defined
precisely enough to detect and trade mechanically, not whether they make money.
Nothing here has run on real market data, and the detectors have not passed the
90% hand labelling gate, so every number the tooling prints describes the code
rather than the market.

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

## Getting to real time trading

[`docs/live.md`](docs/live.md) is the path from here to a live account, gate by
gate. The short version: open a free OANDA practice account, export the token,
and everything up to and including three months of paper trading runs with no
money at risk.

```bash
export OANDA_API_TOKEN=...          # never in the repository
export OANDA_ACCOUNT_ID=101-004-...
export OANDA_ENVIRONMENT=practice

ict fetch --start 2021-01-01 --out data/processed/eurusd_m1.parquet
ict robustness data/processed/eurusd_m1.parquet   # gate 4
ict live data/processed/eurusd_m1.parquet         # dry run; --execute to trade
```

`ict live` sends nothing unless `--execute` is passed, and refuses the live
environment without `--i-understand` on top of that.

## The dashboard

[`docs/dashboard.md`](docs/dashboard.md). One self contained page, about 30KB,
that works offline and can be emailed.

```bash
ict dashboard --journal journal.csv --out dashboard.html
```

It leads with the validation gates rather than a profit number, and says in a
banner when there is no live money in the record. That banner is the reason the
page is worth showing anyone.

Each gate opens to show the commands that would move it, and the first
unfinished one is open on load.

The kill switch is `ict flatten` on the command line, not a button on the page:
a button that closes positions would need a live trading token inside a file
meant to be shared.

## Operating it day to day

[`docs/operating.md`](docs/operating.md). The daily plan, the journal and the
alerts.

```bash
ict plan data/processed/eurusd_m1.parquet --calendar week.csv --account
ict journal journal.csv --daily
```

`ict plan` is read only: it runs the record's seven steps and prints what the
system intends before it acts. The journal appends and never rewrites, writes
each live trade as it closes rather than at the end, and takes its rows from
the broker rather than from what the loop thinks it did. Alerts never stop the
loop: a sink that fails is reported once and left alone.

## News and the AI review layer

[`docs/news.md`](docs/news.md). Two things that can stop a trade, and neither
can start one.

```bash
ict news calendar.csv --parquet data/processed/eurusd_m1.parquet
ict backtest data/processed/eurusd_m1.parquet --calendar calendar.csv \
    --review rules --review-journal decisions.csv
ict review-audit decisions.csv
```

The news gate blocks entries fifteen minutes either side of a high impact
release. It never touches exits: a position open when CPI lands keeps its stop.

The review layer may only skip a trade or shrink it, enforced in the `Verdict`
type rather than in a prompt, because headlines are untrusted input going into
a language model. `ict review-audit` applies the record's own rule: if the
trades the layer blocked would have won more than they lost, switch it off.

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

## Verifying the detectors (gate 1)

[`docs/labelling.md`](docs/labelling.md) is the guide. This is the only thing
blocking the project.

```bash
ict label data/processed/eurusd_m1.parquet --count 100 --timeframe 15m --out labelling.html
# open labelling.html, click candles, press Download labels
ict verify data/processed/eurusd_m1.parquet --labels labels.csv --reviewed reviewed.csv
```

One self contained page with every chart in it, Plotly inlined so it works
offline. Click a candle to mark it, `q a w s e d` pick the concept, `0` records
a chart with nothing on it. Work is saved in the browser as you go.

Pass `--reviewed`. Without it, charts you reviewed and correctly left blank are
skipped, so a detector's false positives on quiet days never count.


This is the gate that decides whether any of the rest is worth building on:
90% agreement with hand labels, per concept. It is manual on purpose. Nothing
here can tell you whether a detector sees what you see.

**1. Export a random sample.**

```bash
ict sample data/processed/eurusd_m1.parquet --count 100 --timeframe 15m \
    --out verification
```

Days are chosen at random rather than picked, so the sample is not quietly
drawn from days the detectors already handle. It writes one chart per day and a
blank `labels.csv`.

**The charts carry no detector marks, deliberately.** Being shown the answers
and then asked to mark the chart independently is not verification: you would
anchor on what is already drawn, agreement would come out high, and a detector
that is systematically wrong would pass the check that exists to fail it. Only
the kill zone shading and session levels are kept, because both are read off
the clock rather than inferred.

Pass `--with-answers` to write the annotated charts and the detector's counts
into a separate `answers/` folder, to review **after** you have finished.

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

## Backtesting the Silver Bullet (Phase 2)

```bash
ict backtest data/processed/eurusd_m1.parquet \
    --from 2021-01-01 --to 2023-12-31 --journal journal.csv
```

Event driven, bar by bar, and pessimistic where the data is ambiguous. It
exits non-zero unless all four pass criteria are met, so it can gate a build.

The rule, from the project record: inside a Silver Bullet hour, a sweep against
the draw, then the first fair value gap pointing at it. Limit at the gap, stop
beyond the sweep extreme, target the draw, and only if that is at least 2R away.

**What the engine assumes, and why it matters.**

- A candle does not record the order it visited its high and low. When one
  candle spans both the stop and the target, the stop is taken. The optimistic
  reading turns losing systems into winning ones on paper.
- An order cannot fill on the candle it was placed from. That decision was
  made from the candle's close.
- Stops are market orders and slip. Targets are limit orders and do not.
  Assuming a stop fills exactly at its price is the most flattering thing a
  backtest can do.
- The spread comes from the data where the file has it, because the spread
  widens exactly when these setups fire.
- An order dies at the end of its window. A Silver Bullet entry filled at
  lunchtime is a different strategy wearing the name.

Risk is enforced, not assumed: 0.5% per trade sized from the stop distance, two
trades a day, one loss ends the session, a 2% daily loss limit and a 6% weekly
drawdown pause. The report counts how often each of those blocked an entry,
because a strategy that only looks good before its limits is not a strategy.

The latest run is written up in [`docs/backtest-results.md`](docs/backtest-results.md),
including what it does and does not demonstrate.

**Pass criteria**, all four, from the project record: profit factor above 1.3,
expectancy above 0.2R, maximum drawdown below 15%, and at least 200 trades. The
report also prints how many parameter combinations you have tried
(`--combinations-tried`), since testing many ICT variants inflates the chance of
a lucky result.

Until `ict verify` passes, the report says so on every run. A profitable
backtest built on unverified detectors is evidence about the code, not about
the market.

## The model set and walk forward (Phase 3)

Phase 2 encoded one model. Phase 3 encodes the remaining six from the project
record and adds the machinery to compare them without fooling ourselves.

| Model | The rule it adds | Window |
| --- | --- | --- |
| `silver_bullet` | Sweep against the draw, then the first gap pointing at it | Three one hour windows |
| `mentorship_2022` | Will not trade until structure has actually shifted | Kill zones |
| `optimal_trade_entry` | Retracement into the 0.62 to 0.79 band of a displacement leg | Kill zones |
| `power_of_three` | Manipulation out of the Asian range, then distribution back through it | London and New York open |
| `judas_swing` | The first move away from the midnight open is the false one | London open |
| `turtle_soup` | Failed break of a level several swings have touched | Any time |
| `sweep_to_sweep` | Sweep one side, target the liquidity resting on the other | Any time |

Every model is a `BaseModel` subclass with one method, `find_setup`, returning
a limit, a stop and a target or nothing. Everything else — window gating, order
life, the minimum R filter and the geometry check — lives in the base class, so
a difference between two models is a difference in the rule and nothing else.

```bash
ict rank data/processed/eurusd_m1.parquet --train-days 40 --test-days 20
```

**Why walk forward rather than one backtest.** Tuning and reporting on the same
data measures how well the search fitted that data. `ict rank` rolls a window
forward: it tunes on `--train-days`, tests on the `--test-days` that follow, and
pools only the test windows into the number it prints. The in sample result is
kept, but only to compute *drift*: in sample expectancy minus out of sample. A
large positive drift is the signature of a parameter search fitting noise, and
it is often the most informative column in the table.

Models are ranked on expectancy per trade in R. Profit factor flatters a model
with three lucky trades, and net profit rewards whichever model traded most.
Empty folds are counted next to the fold total rather than dropped, because a
model that fires twice a year should not be ranked as though it were reliable.

A ranking over generated data, with what each row is worth, is in
[`docs/walk-forward.md`](docs/walk-forward.md). No model passes the project's
criteria there, the top two rows took four trades and ten, and the ordering
does not survive a change of window.

The same `Context` — one pass of every detector over the whole series — is
shared by every model and every fold. Analysing is most of the cost, and the
lookahead guard makes a shared analysis exactly equivalent to re-running the
detectors per fold.

## What is implemented

| Concept | Definition in code |
| --- | --- |
| Swing high / low | High (low) strictly beyond the `n` candles either side, `n = 2` |
| Liquidity pool | Unswept swing that is the extreme of the candles before it; swings within a tolerance of ATR cluster as equal highs/lows |
| Liquidity sweep | Wick a minimum distance beyond a pool that has stood a minimum time, close back inside within `K` candles |
| Break of structure | Close beyond the last confirmed swing, in the trend direction |
| Market structure shift | After a sweep, a close beyond the last opposing swing, where the leg from sweep to break displaced |
| Displacement | Body at least `X` times prior ATR(14) **and** most of the candle's range |
| Fair value gap | Candle 1 high below candle 3 low (inverse for bearish), with mitigation and inversion tracked |
| Order block | Last opposing candle before a displacement leg that breaks structure, with its 50% mean threshold |
| Session levels | Asian high/low, previous day and week high/low, midnight open |

### What counts as liquidity worth sweeping

Three filters in `LiquidityConfig` decide this, and they matter more than any
other parameter in the project. Without them every two bar fractal becomes a
pool and every wick past it becomes a sweep, which fires about ten times a day
on a 15 minute chart: far more often than the concept describes, and enough
false setups to bury a real edge.

| Filter | Default | What it rules out |
| --- | --- | --- |
| `prominence_lookback` | 12 | Swings that are not the extreme of the stretch before them. A fractal inside a larger range is not a level anything rests above. |
| `min_pool_age_candles` | 4 | Levels swept almost as soon as they form. Stops need time to accumulate behind a level. |
| `min_penetration_atr` | 0.10 | Wicks that brush the level rather than run the stops behind it. |

On synthetic data these take the sweep rate from 13.5 a day to 4.3, with
prominence doing most of the work. **The defaults are argued from the
definition, not fitted.** They have never been checked against a hand marked
chart, and tuning them on anything but real data would be fitting to noise.
Re-tune them against `ict verify` before trusting any backtest.

### Swings, and why generated data hides a real bug here

A swing high is at least as high as the `n` candles before it and strictly
higher than the `n` after. The asymmetry is deliberate: a run of candles
sharing the same high is **one** swing, marked at its last candle, rather than
none at all.

Requiring a strictly lower neighbour on both sides looks tidier and fails on
real feeds, which quote to a fixed number of decimals so adjacent candles share
an exact high often. Measured on the same prices at different quantisations:

```
            feed    strict   plateaus   recovered
      raw floats      6092       6092         0%
     5dp EUR/USD      5619       6097         9%
     3dp USD/JPY       336       1513       350%
```

On raw floats the two rules are identical, which is exactly why generated data
cannot show this. On a three decimal feed, the way USD/JPY and tick sized
futures such as NQ and ES quote, the strict rule finds a twentieth of the
swings. Since the project record plans to trade NQ and ES, that matters.

Equal highs are also the liquidity pattern ICT cares most about, so discarding
them is the opposite of what the detector is for.

**Worth checking on real data:** 25.8% of candles are swings at `n = 2`, and
after the prominence filter 57% of consecutive swings share a kind rather than
alternating high, low, high. Structure readings assume alternation, so if that
holds on EUR/USD the sequence may need enforcing.

### What counts as structure

`StructureConfig.prominence_lookback` (12) decides which swings are structure
points at all. Without it every two bar fractal counts, and since nearly every
swing is eventually closed beyond, **break of structure fired 17.2 times a day**
on a 15 minute chart in the test data. That is not a signal, it is a
restatement of "price moved".

With it, breaks fall to 7.6 a day and order blocks, which are built on breaks,
from 0.32 to 0.20 a day.

`mss_prominence_lookback` (6) is deliberately separate and lower. A break of
structure confirms a trend and should break a level the trend is built on; a
shift reverses one, and ICT reads it against the last opposing *short term*
swing. Holding both to the same standard took market structure shifts from 8 to
2 in sixty days, which is stricter than the concept describes.

**This is the least certain setting in the project.** Market structure shifts
are already rare on generated data because displacement is, so the counts here
cannot distinguish a good value from a bad one. Revisit it first against hand
labels.

### Fair value gaps: size, and gaps that are already spent

`min_gap_atr` defaults to 0.20, derived from cost rather than fitted. On
EUR/USD a 15 minute ATR runs around 0.0010 against a spread near 0.00012, so
the spread alone is about 0.12 ATR and a gap narrower than roughly twice that
cannot be entered profitably however good it looks. Recompute it per instrument
from real spread data.

The previous default of 0.05 was **inert**: no gap in sixty days of test data
fell below it, so the detector had no working size filter at all.

Worth checking on real data: **38% of detected gaps were filled within one
candle** and 51% within two. A gap price trades straight back into was never an
imbalance. If that holds on EUR/USD, the three candle definition is catching
wick artefacts and needs a survival requirement, which has to be designed
carefully so the gap's knowable time moves with it rather than leaking the
future.

A mitigated gap is spent. Anything selecting a gap to trade must filter with
`unmitigated(gaps, now)`, not just take the most recent one: resting a limit
order at a level price has already been through and left is waiting for an
imbalance that no longer exists.

### A warning about the displacement threshold

**Do not tune `DisplacementConfig` against synthetic data.** Measured over 60
days of the generated random walk:

```
body / prior ATR       p50 0.39   p90 0.91   p95 1.12   p99 1.41
threshold                                                   1.50
displacement candles                                       0.62%
```

The 99th percentile sits below the threshold, so displacement barely exists and
market structure shifts fire about once a week. That is not a miscalibrated
threshold: a Gaussian random walk has no fat tails, and displacement is a fat
tail event. Real forex has news spikes and session opens; it will clear 1.5
ATR far more often.

Lowering the threshold to make MSS fire more often on generated data would be
calibrating to the absence of fat tails, and the detector would then fire
constantly on real prices. The number to check is the share of displacement
candles on real EUR/USD, not the MSS count here.

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
  cli.py             ingest · fetch · gaps · plot · sample · label · verify
                     backtest · rank · plan · dashboard · flatten · journal
                     news · review-audit · robustness · live · demo
  data/              vendor CSV readers, OANDA client, cleaning, Parquet store
  timeframes/        New York sessions, resampling, the lookahead guard
  detectors/         one module per concept, each a pure function
  plotting/          annotated charts
  backtest/          engine, broker, costs, risk, the seven models, walk forward
  live/              OANDA order adapter and the live loop
  dashboard.py       the gates, the results and the journal, as one page
  labelling.py       the click to mark page for gate 1
  plan.py            the daily routine: bias, path, levels, news, account
  journal.py         append only record of closed trades
  alerts.py          console, file and webhook sinks
  news/              calendar, the entry gate, and the two news playbooks
  review/            the AI review layer and the audit that polices it
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
