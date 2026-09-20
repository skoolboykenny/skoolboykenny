# Silver Bullet backtest: results

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
