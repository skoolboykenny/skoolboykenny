# ICT Trading System

An automated trading engine that encodes Inner Circle Trader concepts as
explicit rules, backtests them honestly, and can trade them through a broker
API. Price logic is deterministic Python. An AI layer reviews setups and may
only shrink or cancel a trade, never create one.

> This is an engineering and research project, not financial advice. Leveraged
> trading carries a high risk of loss.

## Where this actually stands

**Every phase is built. None of it has run against real market data.**

The question the project answers is whether ICT's concepts can be defined
precisely enough to trade mechanically, and then whether doing so has an edge.
The first part is done. The second has not started, because it is gated on
something no amount of code can supply.

| Gate | State |
| --- | --- |
| 1. Detectors agree with hand labels 90% | **Not started.** The tooling is built; the labelling is manual |
| 2. Three years in sample, with costs | Blocked: no real data has loaded |
| 3. Walk forward, out of sample only | Built, run only on a random walk |
| 4. Robustness: sensitivity and Monte Carlo | Built, never run on real data |
| 5. Paper trading, 3 months or 100 trades | Built, never run |
| 6. Small live, 3 months | Not reached |

Every number this tooling has printed so far comes from a Gaussian random walk,
which contains none of the behaviour these models are defined against. Treat
them as evidence about the code and nothing else.

`ict dashboard` renders the table above as a page, with each gate opening to
the commands that would move it.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Python 3.11 or newer. Dependencies are pandas, numpy, pyarrow, plotly and
requests. The AI review layer additionally needs `anthropic`, and is off by
default.

## What to do next

Two steps, in this order. Both are yours; neither is code.

### 1. Get real data

```bash
export OANDA_API_TOKEN=...          # never in the repository
export OANDA_ACCOUNT_ID=101-004-...
export OANDA_ENVIRONMENT=practice

ict fetch --start 2021-01-01 --out data/processed/eurusd_m1.parquet
ict gaps data/processed/eurusd_m1.parquet
```

A free OANDA practice account needs no deposit and supplies both the history
and, later, the execution. Practice and live differ only by hostname, so
everything up to three months of paper trading runs with no money at risk.

`ict fetch` writes one chunk per month, so an interrupted download resumes. Bid
and ask are fetched together, never the mid alone: the spread decides whether a
minute was tradeable and it widens exactly when these setups fire.

### 2. Label the charts

```bash
ict label data/processed/eurusd_m1.parquet --count 100 --timeframe 15m --out labelling.html
# open labelling.html, click candles, press Download labels
ict verify data/processed/eurusd_m1.parquet --labels labels.csv --reviewed reviewed.csv
```

One self contained page with every chart in it, Plotly inlined so it works
offline. Click a candle to mark it, `q a w s e d` pick the concept, `0` records
a chart with nothing on it. Work is saved in the browser as you go.

The charts carry no detector output, deliberately: seeing the code's answer
first turns the gate into a test of whether you can read it.

**Pass `--reviewed`.** Without it, charts you reviewed and correctly left blank
are skipped, so a detector's false positives on quiet days never count, and
over-firing is the failure mode these definitions actually have.

Budget fifteen to twenty hours. It is the only thing on the critical path and
the highest value time in the project. [`docs/labelling.md`](docs/labelling.md)
is the guide.

## Commands

| Command | What it does |
| --- | --- |
| `ict fetch` | Download candles from OANDA, resumable |
| `ict ingest` | Read vendor CSVs into the Parquet store |
| `ict gaps` | Report holes in a stored series, largest first |
| `ict plot` | Annotate any day across 1m, 15m, 1h and 4h |
| `ict label` | Build the click to mark labelling page (gate 1) |
| `ict sample` | Export charts as files, with `--with-answers` for review afterwards |
| `ict verify` | Score hand labels against the detectors |
| `ict backtest` | Run one model over a date range, with costs |
| `ict rank` | Walk forward every model and rank them out of sample |
| `ict robustness` | Gate 4: parameter sensitivity and Monte Carlo |
| `ict news` | Show what a calendar would gate |
| `ict plan` | The daily routine: bias, path, levels, news, account |
| `ict live` | Paper or live trade (dry run unless `--execute`) |
| `ict journal` | Summarise the trade journal |
| `ict review-audit` | Score the AI layer and say whether to keep it |
| `ict dashboard` | The gates, the results and the journal, as one page |
| `ict flatten` | Kill switch: cancel every order, close every position |
| `ict demo` | Generate synthetic candles, to exercise the tooling |

`ict backtest` and `ict robustness` exit non-zero when their criteria fail, so
they can gate a build.

## The two rules that make the results honest

**Nothing is known before it happened.** A swing is not confirmed until the `n`
candles on its right have closed, so `find_swings` records `confirmed_at`
separately from `time`. Pools, levels and gaps carry the same distinction.
Filtering on it is not optional.

**No timeframe may read a candle that has not closed.** A 4h bias taken from a
4h candle still forming is a bias taken from the future, and it is the main
reason ICT backtests look better than they are. Higher timeframe data is read
through `TimeframeStack`, which has no accessor returning a whole frame:

```python
from ict.timeframes.lookahead import TimeframeStack

stack = TimeframeStack.from_minutes(candles)
frames = stack.snapshot(now)   # every timeframe, nothing unclosed
bias_candles = stack.as_of(now, "4h")
```

A property test re-runs the whole backtest on truncated data and asserts that
finished trades do not change. It has caught two real lookahead bugs, one of
them in the Phase 1 pool detector.

## What is implemented

**Detectors.** Swings, liquidity pools, sweeps, displacement, break of
structure, market structure shift, fair value gaps with mitigation and
inversion, order blocks, session levels. Every threshold lives in `config.py`
and the argument for each is in [`docs/detectors.md`](docs/detectors.md).

**Seven models**, each a `BaseModel` subclass whose only job is `find_setup`:
Silver Bullet, the 2022 mentorship model, optimal trade entry, Power of Three,
the Judas swing, Turtle Soup and sweep to sweep. Window gating, order life, the
minimum R filter and the entry geometry check are shared, so a difference
between two models is a difference in the rule.

**A backtest engine** that is pessimistic where a candle is ambiguous: when one
candle spans both the stop and the target the stop is taken, an order cannot
fill on the candle it was placed from, stops slip and targets do not.

**Risk enforced, not assumed.** 0.5% per trade sized from the stop distance,
two trades a day, one loss ends the session, a 2% daily loss limit and a 6%
weekly drawdown pause. The report counts how often each blocked an entry.

**A news gate** that blocks entries fifteen minutes either side of a high
impact release, and never touches exits: a position open when CPI lands keeps
its stop with the broker.

**An AI review layer** that may only skip a trade or shrink it, enforced in the
`Verdict` type rather than in the prompt, because headlines are untrusted text
going into a language model. `ict review-audit` applies the project's own rule:
if the trades the layer blocked would have won more than they lost, switch it
off.

## Layout

```
src/ict/
  config.py          every tunable number
  analysis.py        runs the detectors in dependency order
  cli.py             the eighteen commands above
  data/              vendor CSV readers, OANDA client, cleaning, Parquet store
  timeframes/        New York sessions, resampling, the lookahead guard
  detectors/         one module per concept, each a pure function
  plotting/          annotated charts
  backtest/          engine, broker, costs, risk, the seven models, walk forward
  live/              OANDA order adapter and the live loop
  news/              calendar, the entry gate, and the two news playbooks
  review/            the AI review layer and the audit that polices it
  labelling.py       the click to mark page for gate 1
  dashboard.py       the gates, the results and the journal, as one page
  plan.py            the daily routine: bias, path, levels, news, account
  journal.py         append only record of closed trades
  alerts.py          console, file and webhook sinks
tests/               hand made candle sequences with known answers
```

354 tests. Detection is roughly linear in candle count, about 3 seconds for a
month of 1 minute data, so a three year backtest is a batch job of minutes. The
crossing queries every detector depends on ("when did price first trade beyond
this level?") go through a segment tree in `detectors/_scan.py`.

## Documents

| File | What it covers |
| --- | --- |
| [`docs/labelling.md`](docs/labelling.md) | Gate 1: how to mark charts and what the scores mean |
| [`docs/detectors.md`](docs/detectors.md) | Each detector, and the argument behind its thresholds |
| [`docs/live.md`](docs/live.md) | The gate order, OANDA setup, the path to a live account |
| [`docs/news.md`](docs/news.md) | The calendar gate, the playbooks, the review layer, the audit |
| [`docs/operating.md`](docs/operating.md) | The daily plan, the journal and the alerts |
| [`docs/dashboard.md`](docs/dashboard.md) | The dashboard, and why the kill switch is not on it |
| [`docs/walk-forward.md`](docs/walk-forward.md) | The seven models ranked, and why the ranking means nothing yet |
| [`docs/backtest-results.md`](docs/backtest-results.md) | The Silver Bullet run |
| [`docs/project-record.md`](docs/project-record.md) | The plan, what was built, and what the plan got wrong |
| [`DATA.md`](DATA.md) | The Dukascopy download, kept for reference |
