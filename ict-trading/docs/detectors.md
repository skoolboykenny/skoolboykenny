# The detectors, and the arguments behind them

Each detector is a pure function returning a DataFrame of timestamped events or
zones, and each has unit tests built on hand made candle sequences with known
answers. They hold no state, so they compose: `analysis.py` threads swings into
pools into sweeps into shifts rather than recomputing them.

Every number they use lives in `config.py`. None of these thresholds has been
checked against a hand marked chart, which is gate 1 and the only thing on the
critical path. What follows is the argument for each starting value, so that
when the labels disagree you know what you are overturning.

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
