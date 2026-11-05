# Silver Bullet backtest: results

> **Superseded, 6 October 2026.** Every figure below was produced before two
> bugs were fixed, and both pushed results in the flattering direction.
>
> The candle that filled a limit order was never tested against the stop or the
> target, so a candle that reached the entry and then traded clean through the
> stop left the position open and could later book a win: a trade that should
> have been -1R booked +3R. And the spread gate compared each candle against
> the whole sample's median spread, which is lookahead in a risk check.
>
> Re-running the Silver Bullet over the same 200 days of generated data now
> gives 76 trades, profit factor 1.08, expectancy 0.129R, against the 81
> trades, 0.97 and 0.014R below. The numbers moved in both directions by model,
> which is what a changed trade path does rather than a uniform bias: a trade
> stopped on its fill candle frees the broker earlier, so a different set of
> later setups is taken.
>
> All of it is still generated data and still means nothing about the market.
> The figures are kept rather than quietly restated, because the point of this
> record is that it shows its working.

Run on 2026-09-20 against generated data. **These numbers say nothing about
EUR/USD.** Read the last section before quoting any of them.

Reproduce with:

```bash
ict demo --days 200 --out data/demo_1m.parquet
ict backtest data/demo_1m.parquet --journal journal.csv
```

## Result

207,360 one minute candles over 173 trading days.

| | |
| --- | --- |
| Trades | 81 |
| Net | -129.03 |
| Return | -1.29% |
| Costs paid | 1,462.36 |
| Total R | 1.16 |
| Expectancy | 0.014 R per trade |
| Profit factor | 0.97 |
| Win rate | 18.5% |
| Wins / losses | 15 / 66 |
| Average win | 6.38 R |
| Average loss | -1.43 R |
| Maximum drawdown | 18.1% |

Exits: 68 stops, 13 targets.

### Against the pass criteria

| Criterion | Required | Actual | |
| --- | --- | --- | --- |
| Profit factor | above 1.3 | 0.97 | FAIL |
| Expectancy | above 0.2R | 0.014R | FAIL |
| Maximum drawdown | below 15% | 18.1% | FAIL |
| Out of sample trades | at least 200 | 81 | FAIL |

`ict backtest` exits non-zero while any criterion fails, so it can gate a
build.

## Before and after the detector work

The same range, with every detector setting as it stood before the tuning
pass. The spent gap fix in the strategy is not config controlled, so it is
active in both columns and this understates the difference.

| | trades | win rate | profit factor | expectancy | max drawdown | net |
| --- | --- | --- | --- | --- | --- | --- |
| Before | 121 | 19.0% | 0.59 | -0.473R | 28.8% | -2,538.35 |
| After | 81 | 18.5% | 0.97 | 0.014R | 18.1% | -129.03 |

Forty fewer trades, and the ones removed were disproportionately losers.

**This is not evidence the strategy works.** On a random walk with costs, a
strategy with no edge should land near a profit factor of 1.0 with slightly
negative net, which is where it now sits. Profit factor 0.59 beforehand means
the detectors were actively picking wrong: worse than no edge. Moving to the
noise floor is the most a random walk can demonstrate.

## Two things worth carrying into the real data run

**Costs dominate.** 1,462 paid against a net of -129. At one minute entries the
spread is a large fraction of the risk on every trade, which is why the average
loss is -1.43R rather than -1.00R. If the real spread behaves similarly, cost
sensitivity is the first thing to test, not the last.

**One loss per session is the binding constraint on trade count.** It blocked
3,936 entries, against 311 for the daily trade cap and 141 for the daily loss
limit. With it in place, 81 trades came out of 173 days. The 200 trade minimum
in the pass criteria may be unreachable on a single instrument without a much
longer sample, so either the sample has to grow or that rule has to be tested
as a parameter.

## A number that looks wrong and is not

Total R is +1.16 while net is -129.03. Checked rather than assumed: losing
trades carried a mean risk of 47.51 against 45.97 for winners, because the
losing first half of the run was traded at higher equity than the winning
second half. R normalises by the risk taken and currency does not, so the two
can disagree in sign under compounding.

| | mean risk | sum R | net |
| --- | --- | --- | --- |
| First half | 48.98 | -9.69 | -505.08 |
| Second half | 45.51 | 10.84 | 376.05 |

## What this run does not tell you

The data is a Gaussian random walk. It has no trends, no sessions, no news and
no fat tails, so displacement barely occurs in it and the concepts the strategy
is built on largely do not appear. The run exercises the engine end to end and
nothing more.

Both gates ahead of this remain open:

- The detectors have not passed the 90% hand labelling gate.
- Nothing has run against real market data. Every market data host is refused
  by the build environment's network policy, so the download has to happen
  elsewhere. See `DATA.md`.

Until `ict verify` passes on real EUR/USD, a profitable backtest here would be
evidence about the code rather than about the market.

---

# Real market data, 12 October 2026

**Everything above this line was produced on a synthetic random walk.** This
section is the first result in the project's history from real market data.

## What changed

Not the code. The data. For twelve days the project recorded itself as blocked
on broker credentials and a network policy. A council session on the question
(`docs/council/council-transcript-2026-10-12.md`) found, in its peer review
round, that nobody had checked whether real data was obtainable without the
owner at all. It was. Roughly ten years of real EUR/USD M15 is mirrored on
GitHub, and GitHub is the one host this environment can reach.

The source, its clock, and its five material limitations are documented in
`docs/data-sources.md`. Read that first. The short version: one unnamed retail
broker's M15 export, 178,209 candles from 2015-01-02 to 2022-03-04, clock
established from the data rather than assumed, no bid and ask, ends in 2022.

## How many models could be tested at all

M15 is the finest granularity any reachable host serves, and the project was
designed on 1 minute candles. Over 2015 to 2017, the seven models produced:

| Model | Trades in 3 years |
|---|---|
| `silver_bullet` | 0 |
| `power_of_three` | 0 |
| `turtle_soup` | 0 |
| `judas_swing` | 5 |
| `mentorship_2022` | 19 |
| `optimal_trade_entry` | 99 |
| `sweep_to_sweep` | 135 |

The three zeros are a property of the data, not a verdict on the models. The
Silver Bullet needs a sweep, a displacement, a gap and an entry to fit inside
the 10:00 to 11:00 New York window, which at M15 is four candles. **A model
reported here as untested is untested, not rejected.** Only
`optimal_trade_entry` and `sweep_to_sweep` have samples worth reporting.

## Gate 2: three years in sample, with costs

Default parameters, one combination tried, no tuning. Spread 1.2 pips,
slippage 0.2 pips, 0.5% risk per trade on 10,000.

| | OTE 2015-2017 | OTE 2015-2022 | Sweep to sweep 2015-2017 |
|---|---|---|---|
| trades | 99 | 266 | 135 |
| profit factor | 0.85 | 0.78 | 0.77 |
| expectancy | -0.129R | -0.197R | -0.198R |
| win rate | 16.2% | 16.9% | 19.3% |
| average win | 5.00R | 4.41R | — |
| average loss | -1.12R | -1.14R | — |
| max drawdown | 18.0% | 37.3% | 21.2% |
| net on 10,000 | -699 | -2,453 | -1,321 |

**Both models fail gate 2, and fail it on every criterion they can.** Only one
criterion passes anywhere: OTE clears 200 trades over the full span, which
makes its failure better evidenced rather than better.

The longer span is worse than the shorter one, so this is not one bad window.

## It is not a cost problem

The obvious objection to a losing low win rate system is that the spread ate
it. It did not:

| | gross expectancy | cost drag | net expectancy |
|---|---|---|---|
| OTE 2015-2022 | **-0.082R** | 0.102R | -0.197R |
| Sweep to sweep 2015-2017 | **-0.112R** | 0.083R | -0.198R |

Both are negative **before** a single pip of cost. Costs roughly double a loss
that was already there. A cheaper broker, a tighter spread and zero commission
would not rescue either model. The entry rules, as this code encodes them,
pick worse than a coin toss at this granularity on this data.

## What this result does and does not mean

It does **not** mean ICT has no edge. The honest reading is narrower and it
cuts both ways.

The report that prints on every run says it: until the detectors pass the 90%
hand labelling gate, a profitable result is evidence about the code rather
than the strategy. **The converse holds and is the awkward part.** An
unprofitable result from unverified detectors is also, first of all, evidence
about the code. These numbers cannot yet distinguish "ICT does not work" from
"this code does not implement ICT". Gate 1 is what separates those two, and
gate 1 has not been run.

So the live question is no longer whether to spend the owner's fifteen to
twenty hours before knowing if an edge survives. Gate 2 has answered that: on
the data reachable from here, nothing survives. The question is whether he
wants the negative result to mean something. Without gate 1 the honest
statement is "our encoding of two ICT models lost money on one broker's M15
EUR/USD". With gate 1 passed, it becomes "two ICT models lost money", which is
a claim about the methodology and the thing the project set out to learn.

That is his call, not the code's.

## What would change the picture

In rough order of how much they would change it:

1. **M1 data.** Five of seven models are untested because the bars are too
   coarse, including the Silver Bullet, which the project treats as its
   primary model. This needs OANDA or any MetaTrader demo export, and so it
   needs the owner. It is the single largest gap in this result.
2. **Gate 1**, to make the negative finding mean something about ICT rather
   than about this repository.
3. **A second data source**, since one undocumented broker feed is one sample
   of one. Gate 4 exists for this.
4. Parameter work, listed last deliberately. With both models negative before
   costs, tuning them to profit on this data would be fitting noise, and the
   unattended runner is forbidden from doing it for exactly that reason.

Gates 3 to 6 were not run. Gate 2 failed, and the project's own rule is that a
failed gate is not a gate that passed.

---

# Four instruments, 5 November 2026

The gate 2 result above rested on one instrument, and `docs/data-sources.md`
named that as its weakness: one undocumented broker feed at one granularity is
one sample of one. The mirror carries twelve symbols, so the two models that
trade at M15 were run across four of them over the same 2015 to 2022 span.

## A bug found on the way

The mirror quotes prices as integer points, and the reader divided every
symbol by 100,000. That is right for the major dollar pairs and wrong for the
yen crosses, which are quoted to three digits, and for gold, quoted to two.
USD/JPY read at the dollar scale gives 0.80163 where the price is 80.163.

This would not have failed loudly. The detectors work in multiples of ATR and
are therefore scale invariant, so they would have produced a full set of
trades. The spread and slippage in the cost model are absolute prices, so the
costs would have been a thousand times too large relative to price, and the
result would have looked like a catastrophic edge rather than a broken load.

The scale is now looked up per symbol, an unknown symbol is refused rather
than guessed, and `--point-scale` overrides it. Prices were then checked
against known history: GBP/USD bottoms at 1.1417, which is the Brexit low;
gold spans 1047 to 2070, which is the December 2015 low to the August 2020
high.

## The results

Costs set per instrument, because a pip is 0.0001 on EUR/USD and 0.01 on
USD/JPY while gold trades in dollars. EUR/USD 1.2 pips, GBP/USD 1.5, USD/JPY
1.2, gold 30 cents, each with slippage near a sixth of the spread. In relative
terms these are all close to 1.1 basis points, so no instrument was given a
cheaper ride than another.

| Instrument | Model | Trades | Profit factor | Expectancy | Drawdown |
|---|---|---|---|---|---|
| EUR/USD | optimal trade entry | 266 | 0.78 | -0.197R | 37.3% |
| GBP/USD | optimal trade entry | 293 | 0.55 | -0.403R | 47.9% |
| USD/JPY | optimal trade entry | 167 | 1.04 | +0.054R | 11.7% |
| Gold | optimal trade entry | 179 | 0.73 | -0.252R | 25.3% |
| EUR/USD | sweep to sweep | 303 | 0.83 | -0.140R | 25.1% |
| GBP/USD | sweep to sweep | 289 | 0.71 | -0.230R | 36.4% |
| USD/JPY | sweep to sweep | 226 | **1.24** | **+0.200R** | 11.8% |
| Gold | sweep to sweep | 218 | 0.93 | -0.048R | 12.7% |

EUR/USD reproduces the earlier run exactly, which is the reproducibility check
this table needed before any of the rest of it means anything.

Before costs:

| Instrument | OTE gross | Sweep to sweep gross |
|---|---|---|
| EUR/USD | -0.082R | -0.041R |
| GBP/USD | -0.243R | -0.139R |
| USD/JPY | **+0.151R** | **+0.298R** |
| Gold | -0.125R | +0.039R |

## What it says

**The negative finding holds, and is now much better evidenced.** Six of eight
cells are negative after costs, five of eight are negative before costs, and
the two largest samples on the two most liquid pairs fail decisively on every
criterion. This is no longer one instrument's result.

**USD/JPY is the exception, and it is positive on both models.** Sweep to
sweep reaches a 1.24 profit factor, +0.200R expectancy and an 11.8% drawdown
over 226 trades, which clears the trade count and the drawdown limit and falls
short on profit factor, where the gate asks for 1.3. It is positive before
costs by a wider margin than it is after, so it is not a cost artifact, and
the per-instrument costs were set to the same relative level everywhere so it
was not handed a cheaper ride.

**It still does not pass, and it should not be treated as an edge.** Running
eight cells and reporting the best one is the multiple comparisons trap, and a
single marginal pass out of eight is exactly what noise produces. Two models
agreeing on the same instrument is weaker evidence than it looks, because they
read the same sweeps on the same bars and their trades are not independent.

So gate 3 was **not** run on it. Gate 2 did not pass, the project's own rule is
that a failed gate is not a passed gate, and walk forward is specifically the
gate that kills a result which came from picking the best instrument. Moving
to it now, on the one cell that looked good, would be using the gates in the
order that flatters rather than the order that tests.

What USD/JPY has earned is a decision, not a promotion: whether it is worth
putting one instrument through walk forward knowing the selection bias, and
how that result should be discounted if it survives. Under the rule in
`KENAOPE.md` that belongs to the council and to the owner, not to a unilateral
next run.

Nothing here changes gate 1. Every number above still cannot distinguish a
finding about ICT from a finding about this code.
