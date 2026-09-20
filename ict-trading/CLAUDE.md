# CLAUDE.md

## Project

An automated trading engine that encodes Inner Circle Trader (ICT) concepts as
explicit rules, backtests them honestly, and later trades autonomously through
a broker API. Price logic is deterministic Python. An AI review layer is added
later and may only reduce or cancel trades.

Owner: Ryan Kenaope. Use UK English in all docs, comments and output. Do not
use " - " as a dash in prose.

## Current phase: Phase 1, data and detectors

Goal: load 1 minute data, build the timeframe stack, and implement verified ICT
detectors with chart plots. No strategy, no broker, no AI yet.

### Deliverables

1. Data loader for EUR/USD 1 minute OHLC (Dukascopy or HistData CSV). Store as
   Parquet. Handle gaps, weekends and duplicate rows.
2. Timezone handling: all timestamps stored in UTC, with a helper converting to
   America/New_York (DST aware). Sessions and kill zones are defined in New
   York time.
3. Resampler building 15m, 1h and 4h candles from 1 minute data, aligned to New
   York time.
4. Lookahead guard: a function returning only higher timeframe candles fully
   closed at a given 1 minute timestamp. Every detector and strategy must use
   it.
5. Detectors, each a pure function returning a DataFrame of events or zones
   with timestamps:
   - swing highs and lows (N bars either side, default N = 2)
   - liquidity pools: unswept swings and equal highs/lows within a tolerance
     (fraction of ATR)
   - liquidity sweeps: wick beyond a pool, close back inside within K bars
   - displacement: body at least X times ATR(14), default X = 1.5
   - market structure shift: close beyond last opposing swing after a sweep,
     with displacement
   - fair value gaps (bullish and bearish), with mitigation tracking
   - order blocks: last opposing candle before a displacement leg that breaks
     structure
   - session levels: Asian range, previous day and week high/low, midnight open
6. Plotting: annotated candlestick charts (plotly) showing detected swings,
   pools, sweeps, MSS, FVGs and order blocks for any date and timeframe.
7. Verification tooling: a script that exports random chart samples so
   detectors can be compared against hand labels.

### Engineering standards

- Python 3.12, pandas, numpy, pyarrow, plotly, pytest. Keep dependencies
  minimal.
- Structure: `src/ict/data`, `src/ict/timeframes`, `src/ict/detectors`,
  `src/ict/plotting`, `tests/`.
- Every detector has unit tests built on small hand made candle sequences with
  known answers.
- All parameters live in one config file; no magic numbers in detector code.
- Type hints and short docstrings on public functions.
- No secrets in the repo. Future API keys come from environment variables.

### Definition of done for Phase 1

- `pytest` passes.
- A command plots any chosen day with all detectors annotated on 1m, 15m, 1h
  and 4h.
- A README explains setup, data download and how to run the plots.

## Later phases (do not build yet)

2. Silver Bullet backtest with spread, commission and slippage.
3. Remaining models: 2022 model, OTE, Power of Three, Judas swing, Turtle Soup,
   sweep to sweep.
4. News module (calendar gate, directional and spike correction playbooks) and
   AI review layer.
5. Broker integration (OANDA practice account first), dashboard, journal,
   alerts.
6. Live only after walk forward and paper trading gates pass.

## Project record

The full research and build plan, the council verdict, the automation design
and the roadmap are in `docs/project-record.md`.
