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
