# Gate 1: labelling the charts

This is the only thing blocking the project, it takes a few evenings, and no
amount of code can do it for you. That is the point of it.

## What the gate is

The detectors must agree with a human at least 90% of the time, over 100 charts
per concept. Until they do, every backtest result is a statement about the
code and not about the market, because a "sweep" the code found might not be
one.

Agreement is matched over everything either side claimed, so it punishes both
directions. A detector that finds every sweep you marked **and** forty you did
not still fails. That is deliberate: the sweep detector was firing 13.5 times a
day before tuning, and over-firing is the failure mode these definitions have.

## Getting the charts

```bash
ict label data/processed/eurusd_m1.parquet --count 100 --timeframe 15m --out labelling.html
```

One self contained page with every chart in it. Plotly is inlined rather than
fetched, so it works on a train with no signal, and the file can be copied to
another machine and still open. A hundred 15 minute charts comes to about 5MB.

Open it with `file:///path/to/labelling.html`. No server, no install.

**Start on 15 minute charts.** A day is 76 candles rather than 1,440, the
structure is visible without zooming, and the detectors run on the same
timeframe you marked, so a disagreement is a real disagreement rather than a
resolution artefact. Do 1 minute afterwards if the 15 minute results hold up.

## Marking

Click any candle to mark it. The click snaps to the nearest candle, so you
never read a timestamp off the screen or type one.

| Key | Concept |
| --- | --- |
| `q` | swing high |
| `a` | swing low |
| `w` | sweep |
| `s` | mss |
| `e` | fvg |
| `d` | order block |

| Key | Action |
| --- | --- |
| `0` | nothing here, and move on |
| `u` | undo the last mark |
| `←` `→` | previous and next chart |

Clicking the same candle twice with the same concept removes the mark, which is
the quickest way to fix a misclick. Dragging pans the chart and never leaves a
mark.

Work is saved in the browser as you go, so closing the tab does not lose an
evening. When you are done, press **Download labels**: you get `labels.csv` and
`reviewed.csv`.

### `0` matters more than it looks

A chart where you correctly saw no sweeps is evidence, and it is the evidence
that catches a detector firing on quiet days. Press `0` rather than skipping
with `→`, or that chart never enters the score.

This was a real hole in the gate until it was fixed. The scorer only looked at
charts carrying at least one label, so a chart you reviewed and left blank
contributed nothing, and every false positive on it was invisible. A detector
that over-fired on exactly the quiet days would have passed the gate built to
fail it.

## What you are marking

You are marking what **you** see, by the definitions you trade. Not what you
think the code will find. If you are unsure whether something is a sweep, that
uncertainty is information: mark it the way you would trade it, and if the
detector disagrees, one of you is wrong and it is worth finding out which.

Do not open the detector output first. `ict sample --with-answers` exists for
reviewing afterwards and the folder is separate on purpose. Anchoring is not a
theoretical risk here: seeing the code's answer first turns the gate into a
test of whether you can read its output.

## Scoring

```bash
ict verify data/processed/eurusd_m1.parquet --labels labels.csv --reviewed reviewed.csv
```

Pass `--reviewed`. Without it the command warns you, and the number it prints
is flattering and wrong.

It exits non-zero below 90%, and prints recall and precision separately so you
can see which way a detector is failing:

- **Low recall, high precision** — the detector is too strict. It misses things
  you see. Loosen the threshold.
- **High recall, low precision** — the detector fires too often. This is the
  usual one. Tighten prominence, or the minimum size.

Tune against these numbers, never against backtest results. A parameter that
improves a backtest and worsens agreement is a parameter fitted to one sample
of price history.

The setting to look at first is `mss_prominence_lookback` in `config.py`. It is
flagged there as the least certain in the project: the market structure shift
uses a lower prominence (6) than break of structure (12), argued from the
definition rather than measured, and hand labels are the only thing that can
settle it.

## How long this takes

About 15 to 20 hours for 100 charts across six concepts, with the tuning
iterations. Two or three weeks of evenings.

It will feel slow and it is the highest value time in the whole project. Every
number the system has produced so far rests on it, and the most likely outcome
of the project as a whole is that this step tells you something the backtests
never could.

## When it passes

```bash
ict fetch --start 2021-01-01 --out data/processed/eurusd_m1.parquet   # gate 2
ict backtest data/processed/eurusd_m1.parquet --verified               # gate 2
ict rank data/processed/eurusd_m1.parquet --train-days 365 --test-days 90   # gate 3
ict robustness data/processed/eurusd_m1.parquet                        # gate 4
```

`docs/live.md` has the rest of the order.
