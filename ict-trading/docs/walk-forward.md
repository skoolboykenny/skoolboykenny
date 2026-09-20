# Walk forward ranking of the seven models

Generated data. **Not a result.** Read "how to read this" before the table.

## What was run

```
ict rank <parquet> --train-days 40 --test-days 20
```

200 days of synthetic 1 minute candles, EUR/USD shaped, from `ict demo`. Four
parameter combinations per model (`minimum_r` 1.5 and 2.0 crossed with
`stop_buffer` 0.1 and 0.25), tuned on a rolling 40 day window and tested on the
20 days after it. Seven folds. Only the test windows are pooled into the
numbers below; the training windows appear only in the drift column.

## The table

```
model                trades   win%     PF   exp R  total R   maxDD   drift  folds
------------------------------------------------------------------------------
power_of_three            4  75.0%   6.53   1.472     5.89    0.5%  -0.576  (3 empty)
judas_swing              10  50.0%   2.51   0.889     8.89    1.7%  -0.499  (2 empty)
silver_bullet            57  17.5%   1.14   0.180    10.27   12.6%  -0.530      7
optimal_trade_entry      40  15.0%   0.84  -0.168    -6.71    7.9%   0.182      7
sweep_to_sweep           40  15.0%   0.63  -0.383   -15.30   10.7%  -0.053      7
mentorship_2022          15  13.3%   0.37  -0.650    -9.75    4.9%   0.708  (1 empty)
turtle_soup             101   5.0%   0.40  -0.934   -94.32   50.6%  -0.100      7
```

`drift` is in sample expectancy minus out of sample expectancy. A large
positive drift means the tuning fitted noise. The machine readable version is
in [`walk-forward-ranking.csv`](walk-forward-ranking.csv).

No model passes the project's criteria: profit factor above 1.3, expectancy
above 0.2R, maximum drawdown below 15%, at least 200 trades. The trade count
alone rules every one of them out.

## How to read this

**The top two rows are noise, and the fold column says so.** Power of Three
took four trades across seven folds and was empty in three of them; the Judas
swing took ten and was empty in two. A profit factor of 6.53 on four trades
carries no information, and one loss would move either row to the bottom of the
table. Expectancy per trade is the right metric for comparing models that trade
at different rates, but it cannot rescue a sample of four. Treat anything under
roughly thirty trades as "did not trade enough to say".

**The ordering is not stable, which is the most useful thing here.** An earlier
run over 120 days with two combinations put turtle soup top of the rows that
actually traded, at +14.49R from a 6.4% win rate. On 200 days with four
combinations it is bottom, at −94.32R with a 50.6% drawdown over 101 trades.
Nothing about the model changed. The same rule read as the best and the worst
of the set depending on the window, which is what a model with no edge looks
like when the sample is too small to tell.

**Turtle soup's shape is worth understanding even so.** A hundred trades at a
5% win rate, aiming for a distant target with 1R at stake, is a lottery
profile: rare large winners paying for many small losers. Some ICT models
genuinely look like this. So does anything that risks 1R for a far target on a
random walk. The two cannot be separated on generated data, and the 50.6%
drawdown says this particular version would not be survivable either way.

**The Silver Bullet tops the rows that traded enough to speak**, at 0.180R
expectancy over 57 trades and a 1.14 profit factor. It still fails every
criterion, and 12.6% drawdown is close to the 15% limit. Phase 2 measured 0.97
profit factor over one parameter set and no walk forward; 1.14 out of sample
here is the same thing within noise, not an improvement.

**Positive drift marks the models whose tuning fitted noise**: `mentorship_2022`
at 0.708 and `optimal_trade_entry` at 0.182 both did better in sample than out.
Negative drift is not a virtue; it means the test window happened to be kinder
than the training one, which on a random walk is chance.

## What this does and does not show

It shows the machinery works: seven models run through one engine, share one
analysis, tune and test on separate windows, and produce a comparable ordering
with the small samples flagged rather than hidden.

It shows nothing about the models. The data is a Gaussian random walk with no
trend, no session structure, no fat tails and no liquidity. Every ICT concept
these models look for is defined against behaviour the data does not contain.
A model that scores well here has found a pattern in the random number
generator, and as the 120 day comparison shows, it will not score well twice.

Two further caveats, both on the record already:

- The detectors have not passed the 90% hand labelling gate, so what the models
  read as a sweep or a shift may not be one.
- Nothing has run on real market data. See `DATA.md`.

Rerun this on real EUR/USD, after the gate passes, over several years, before
reading any row of it as a statement about a model.
