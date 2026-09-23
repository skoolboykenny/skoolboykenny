# CLAUDE.md

## Project

An automated trading engine that encodes Inner Circle Trader (ICT) concepts as
explicit rules, backtests them honestly, and later trades autonomously through
a broker API. Price logic is deterministic Python. An AI review layer is added
later and may only reduce or cancel trades.

Owner: Ryan Kenaope. Use UK English in all docs, comments and output. Do not
use " - " as a dash in prose.

## Phase 1: data and detectors

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

### Status

Every deliverable above is built and tested, and the definition of done is met
on the two points code can meet:

- `pytest` passes (104 tests).
- `ict plot <parquet> --date <day>` annotates 1m, 15m, 1h and 4h.
- `README.md` covers setup, data and plotting; `DATA.md` covers the download.

**The 90% gate is not met and cannot be met by writing code.** The tooling to
run it exists (`ict sample` exports charts and a blank `labels.csv`, `ict
verify` scores them and exits non-zero below the gate), but the labelling is
manual. Until 100 charts per concept have been marked and scored, the detectors
are plausible rather than verified, and no Phase 2 result should be trusted.

Nothing has been run against real market data. The download step needs a
machine that can reach `datafeed.dukascopy.com`; see `DATA.md`.

Do not start Phase 2 before the gate passes.

## Phase 2: Silver Bullet backtest

Started at the owner's instruction before the Phase 1 gate passed. The
machinery is built and tested; the numbers it produces are not yet meaningful.

Built: `src/ict/backtest/` with an event driven engine, a simulated broker, a
cost model, the risk limits from the project record, the Silver Bullet strategy
and a results report against the four pass criteria. `ict backtest` runs it.

The engine is pessimistic where a candle is ambiguous, refuses to fill an order
on the candle it was placed from, slips stops but not targets, and is covered
by a property test that re-runs the whole backtest on truncated data and
asserts finished trades do not change. That test caught two real lookahead
bugs, one of them in the Phase 1 pool detector.

Sampling exports unmarked charts: the labelling chart must not show the
detector's own answers, or anchoring inflates the score.

Detector tuning so far: the liquidity pool and sweep definitions were
tightened (prominence, pool age, penetration), taking sweeps from 13.5 a day to
4.3. The MSS detector was **not** threshold tuned, deliberately: on the
synthetic random walk the 99th percentile of body over prior ATR is 1.41
against a 1.5 threshold, so displacement is nearly absent because the data has
no fat tails. Lowering it there would calibrate to noise. Only a definitional
fix was made, allowing displacement to come from any candle in the leg between
the sweep and the break rather than the breaking candle alone.

The FVG size threshold was inert (0.05 ATR rejected nothing) and is now 0.20,
argued from spread rather than fitted. The Silver Bullet was resting orders at
already mitigated gaps in 82% of its setups and now filters with
`unmitigated(gaps, now)`.

Structure points now need prominence too: break of structure fired 17.2 times
a day because every fractal counted, and is now 7.6. MSS uses a separate,
lower prominence (6 against 12) because it breaks a short term swing rather
than a major one; that setting is the least certain in the project and should
be revisited first against hand labels.

Swings allow plateaus: a run of equal highs is one swing at its last candle.
The strict rule found 336 swings against 1,513 on data quantised to three
decimals, the way USD/JPY and tick sized futures quote, and the two rules are
identical on raw floats, so generated data cannot show this. Noted for real
data: 57% of consecutive prominent swings share a kind rather than
alternating.

A full run over 200 days of generated data is written up in
`docs/backtest-results.md`: profit factor 0.97, expectancy 0.014R, 81 trades,
all four pass criteria failed. The detector work took it from 0.59 to 0.97,
which means it stopped picking actively wrong rather than that it found an
edge; 0.97 is the noise floor for a random walk after costs.

**Still true: the detectors have not passed the 90% gate and nothing has run on
real data.** The report states this on every run unless `--verified` is passed.
Do not act on a result until `ict verify` passes on real data.

## Phase 3: the remaining models and walk forward

The six models the record lists beyond the Silver Bullet are encoded: the 2022
mentorship model, optimal trade entry, Power of Three, the Judas swing, Turtle
Soup and sweep to sweep. Each is a `BaseModel` subclass whose only job is
`find_setup`. Window gating, order life, the minimum R filter and the entry
geometry check are shared, so a difference between two models is a difference
in the rule rather than in the plumbing.

`src/ict/backtest/strategy.py` holds the shared `Context`: one pass of every
detector over the whole series, reused by every model and every fold. Analysing
is most of the cost, and the lookahead guard makes a shared analysis exactly
equivalent to re-running the detectors per fold.

`src/ict/backtest/walkforward.py` and `ict rank` tune on a rolling training
window, test on the window after it, and pool only the test windows into the
reported number. In sample results are kept solely to compute drift, in sample
expectancy minus out of sample, which is the signature of a search fitting
noise. Models are ranked on expectancy per trade in R, because profit factor
flatters a model with three lucky trades and net profit rewards whichever model
traded most. Empty folds are counted next to the fold total rather than
dropped.

Writing the tests found two real defects, both now fixed centrally:

- A model could return a long whose stop sat above its own entry, when the gap
  opened below the swept low. Risk being an absolute distance hid it. `_finish`
  now insists on `stop < limit < target` for a long and the inverse for a
  short.
- Setups whose whole risk was narrower than the spread filled at or past their
  own stop, booking the loss before price moved. The engine refuses them and
  counts them under "stop inside cost", since a model never sees the spread and
  cannot check this itself.

The walk forward ranking on generated data is in `docs/walk-forward.md`. It
orders the code, not the models: on a random walk there is nothing to find, and
none of these detectors has passed the 90% gate. The clearest evidence of that
is in the document itself. Turtle soup came top of the rows that traded on 120
days and bottom on 200, at +14.49R and then -94.32R, with nothing about the
model changed. An ordering that does not survive a change of window is not an
ordering.

## Phase 4: the path to live

Built ahead of the earlier gates because the data blocker made everything else
theoretical, and because one OANDA integration clears it.

`src/ict/data/oanda.py` is the v20 client: paged candle download with bid and
ask together, the price stream, and the account and order endpoints. Credentials
come from `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID` and `OANDA_ENVIRONMENT` and
never from the repository. `ict fetch` writes one chunk per month so a download
resumes, and drops incomplete candles on the way in.

`src/ict/backtest/robustness.py` is gate 4. Parameter sensitivity moves one
field at a time, one step either side, and reports the share of neighbours that
stayed profitable; crossing every field would be a parameter search wearing a
robustness test's clothes. Monte Carlo reshuffles trades for the drawdown
distribution and resamples with replacement for a confidence interval on
expectancy. `ict robustness` exits non-zero unless both halves pass.

`src/ict/live/` is gates 5 and 6. The loop reuses the backtest's detectors,
models and risk manager unchanged, so paper trading measures what was
backtested. It holds back the forming candle, attaches every stop and target at
fill time so a position is never naked, expires orders with their window,
reconciles against the account before each decision, and halts finally on a
stale stream, a drawdown past the guard or a losing run. `ict live` is a dry run
unless `--execute` is passed, and refuses the live environment without
`--i-understand`.

The sequence, and what is still blocking, is in `docs/live.md`. Gate 1 remains
the true blocker: it is manual labelling and no amount of code substitutes for
it.

## Phase 5: news module and AI review layer

`src/ict/news/` is the calendar, the gate and the two playbooks. The gate is a
risk check, so it narrows the tradeable window before a model is asked rather
than being something a model consults. It blocks entries and never exits: a
position open when CPI lands keeps its stop with the broker. Surprises are
scaled by each event's own history, using only earlier releases, because an
unscaled surprise ranks every payroll release above every inflation release on
quoting units alone. `NewsCostModel` widens the spread for the first sixty
seconds; a news result produced without it should be thrown away.

`src/ict/review/` is the AI layer. It may only skip a trade or shrink it, and
that is enforced in the `Verdict` type rather than in the prompt, because
headlines are untrusted text going into a language model and a prompt is not a
boundary. The worst a successful injection can do is skip a trade. An
unparseable reply becomes a take, since a parsing failure is the reviewer's
fault and the strategy should not pay for it. `RuleReviewer` is the default and
needs no API.

The audit is the part that matters, and it needed real work to be more than a
comment. The engine runs a shadow broker so a blocked trade's R can be known,
and the shadow carries its own risk manager: blocking a trade means the loss
never happens, so the session limits never trip and the strategy sees setups it
would never have reached. Without that the counterfactual read -277R against an
unreviewed -26R on the same data. A blocked setup also occupies the engine for
the order's life rather than being re-reviewed every candle, which was turning
one refusal into hundreds of decisions and, against a real API, hundreds of
calls.

`ict news`, `--calendar` and `--review` on backtest and live, and
`ict review-audit`, which exits non-zero when the layer should come off.
`docs/news.md` covers it.

Both are filters on a strategy that has not passed gate 1. A filter on an
unverified strategy is a filter on a bug. The review layer's honest default is
off until its own audit says otherwise on real data.

## Phase 6: the daily loop, journal and alerts

`src/ict/plan.py` is the record's seven step routine, run before Asia. It is
read only, so it can be run at any time against any account or none, and `--at`
rebuilds it for any past moment through the same point in time accessors the
engine uses. The bias is the same `draw_on_liquidity` the models use rather
than a second opinion: a plan that disagreed with the engine would describe a
system nobody is running. A day with no calendar and a day with no releases do
not read the same, and an open position turns the plan to no trade.

`src/ict/journal.py` appends and never rewrites, because the record's own
answer to "this sounds like every scam trading bot" is a visible, honest
record. Live rows are written one trade at a time as each closes, since a
process that dies holding its results has no results, and they come from the
broker rather than from what the loop thinks it did. Every row carries whether
it was backtest, paper or live. Trades opened outside every kill zone appear
under their own name so the breakdown adds up; they were being dropped silently
because pandas 3 keeps NA through `astype(str)` and groupby drops NaN keys.

`src/ict/alerts.py` has two rules. An alert never stops the loop: a sink that
raises is reported once and then left alone, since retrying a broken webhook on
every fill turns one outage into a busy loop. And a halt is loud while
everything else stays quiet enough to keep reading, because an alerting system
people mute looks like coverage.

`ict plan`, `ict journal`, and `--trade-journal` and `--alert-log` on live.
`docs/operating.md` covers it.

None of this changes the gate order. Gate 1 is still unstarted and still the
only thing on the critical path.

## Gate 1 tooling

`src/ict/labelling.py` and `ict label` replace the CSV workflow, which was
never going to be finished: it asked for a timestamp read off a chart by eye
and typed into a file, six hundred times. The page is self contained with
Plotly inlined, so it works offline and can be copied between machines. A click
snaps to the nearest candle, `q a w s e d` select the concept, `0` records a
chart with nothing on it, and work is saved to the browser as it goes. It shows
no detector output, which is the whole point of the gate.

Plotly's pan handler consumes `mouseup` on the drag layer, so the click handler
listens for `click` with `mousedown` recording the start position; `plotly_click`
alone only fires over a candle body and misses half the clicks in a session.

**A real hole in the gate was fixed here.** `score()` grouped by the charts
appearing in the labels, so a chart reviewed and correctly left blank
contributed nothing and every false positive on it was invisible. A detector
that over-fired on quiet days would have passed the gate built to catch exactly
that. `score()` now takes `reviewed`, the page writes `reviewed.csv`, and
`ict verify` warns loudly when it is not given.

`docs/labelling.md` is the guide to follow.

## Phase 7: the dashboard

`src/ict/dashboard.py` and `ict dashboard`. One self contained page, about
30KB, hand built SVG rather than a plotting library so it stays emailable,
needs no network, and follows one mark spec.

It leads with the validation gates rather than a profit number, and banners
plainly when there is no live money in the record. Each gate opens to show what
would move it: what it asks for, the commands in order, and what done looks
like. The first unfinished gate is open on load, so the page answers "what do I
do next" without a click. Native `<details>`, so no ARIA and no script. The record's outsider
verdict is the reason: a visible, honest journal is what makes anyone trust
this, and a page that opens with an equity curve while burying the unverified
detectors is the genre the project is trying not to be in. No gate is marked
passed by the absence of a failure.

Colour does one job. Blue above zero and red below is polarity, not identity,
so it uses the validated diverging pair (worst adjacent CVD separation 21.6
light, 19.2 dark). The by-model and by-session bars use a single hue because
the row labels already carry identity. Dark mode is its own steps, under both
the media query and the theme attribute.

**The kill switch is deliberately not on the page**, which is the one place
this departs from the record. The page exists to be sent to people, and a
button that flattens an OANDA account would need a live trading token inside a
shared file. `ict flatten` does it from the command line, where the token is
already in the environment and the confirmation is a person. A test asserts the
page contains no credential, no fetch, and no broker hostname.

`docs/dashboard.md` covers it.

## Later phases (do not build yet)

1. Live only after every gate in `docs/live.md` passes.

## Project record

The full research and build plan, the council verdict, the automation design
and the roadmap are in `docs/project-record.md`.
