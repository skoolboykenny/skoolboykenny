# Walk forward ranking of the seven models

Generated data. **Not a result.** Read the last section before the table.

## What was run

```
ict rank <parquet> --train-days 40 --test-days 20 --minimum-r 1.5 2.0
```

120 days of synthetic 1 minute candles, EUR/USD shaped, from `ict demo`. Two
parameter combinations per model, tuned on a rolling 40 day window and tested
on the 20 days after it. Three folds. Only the test windows are pooled into the
numbers below; the training windows appear only in the drift column.

## The table

```
model                trades   win%     PF   exp R  total R   maxDD   drift  folds
------------------------------------------------------------------------------
judas_swing               3  66.7%  10.63   3.450    10.35    0.5%  -5.076  (1 empty)
power_of_three            2 100.0%    inf   1.594     3.19    0.0%   0.104  (1 empty)
turtle_soup              47   6.4%   1.12   0.308    14.49   17.5%  -1.195      3
sweep_to_sweep           22  13.6%   1.02   0.035     0.77    4.2%  -0.363      3
optimal_trade_entry      21  14.3%   0.94  -0.040    -0.83    4.5%  -0.665      3
silver_bullet            21   4.8%   0.65  -0.435    -9.14   10.5%   0.374      3
mentorship_2022           8   0.0%   0.00  -1.245    -9.96    5.0%   1.303      3
```

`drift` is in sample expectancy minus out of sample expectancy. A large
positive drift means the tuning fitted noise. The machine readable version is
in [`walk-forward-ranking.csv`](walk-forward-ranking.csv).

No model passes the project's criteria: profit factor above 1.3, expectancy
above 0.2R, maximum drawdown below 15%, at least 200 trades. The trade count
alone rules every one of them out, which is the honest reading of 120 days.

## How to read this

**The top two rows are noise, and the ordering knows it.** The Judas swing took
three trades and Power of Three took two, each with an empty fold. A profit
factor of 10.63 on three trades and an infinite one on two carry no
information: one loss would move either to the bottom of the table. Expectancy
per trade is the right metric for comparing models that trade at different
rates, but it cannot rescue a sample of two. Anything with fewer than about
thirty trades here should be read as "did not trade enough to say".

**Turtle soup is the interesting row, and not in a good way.** Forty seven
trades, a 6.4% win rate, and +14.49R. Three winners paid for forty four losers.
That is a real shape, some ICT models genuinely look like this, but it is also
exactly what a random walk produces when a model risks 1R to reach a distant
target: the wins are large because the target is far, and the hit rate is low
for the same reason. A 17.5% drawdown to earn it is above the project's 15%
limit. The two cannot be separated on generated data.

**The Silver Bullet looks worse here than in the Phase 2 report** (0.65 profit
factor against 0.97). That report ran 200 days with one parameter set and no
walk forward. This is 60 out of sample days with the parameters chosen on the
40 days before each. The difference is mostly the sample, and partly the point:
picking parameters on one window and trading them on the next is harder than
picking them once over everything.

**Positive drift marks the models whose tuning fitted noise**: `mentorship_2022`
at 1.30 and `silver_bullet` at 0.37 both did better in sample than out.
Negative drift is not a virtue, it means the test window happened to be kinder
than the training one, which on a random walk is chance.

## What this does and does not show

It shows the machinery works: seven models run through one engine, share one
analysis, tune and test on separate windows, and produce a comparable ordering
with the small samples flagged rather than hidden.

It shows nothing about the models. The data is a Gaussian random walk with no
trend, no session structure, no fat tails and no liquidity. Every ICT concept
these models look for is defined against behaviour the data does not contain.
A model that scores well here has found a pattern in the random number
generator.

Two further caveats, both on the record already:

- The detectors have not passed the 90% hand labelling gate, so what the models
  read as a sweep or a shift may not be one.
- Nothing has run on real market data. See `DATA.md`.

Rerun this on real EUR/USD, after the gate passes, over several years, before
reading any row of it as a statement about a model.
