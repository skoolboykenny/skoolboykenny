# Data sources

Every number this project reports depends on where the candles came from, so
the provenance lives here rather than in a commit message. Read this before
trusting any figure in `docs/backtest-results.md` or `docs/walk-forward.md`.

## What the build environment can reach

The cloud environment this project is built in sends all outbound traffic
through a proxy with an allow list. Checked on 2026-10-12:

| Host | Purpose | Reachable |
|---|---|---|
| `raw.githubusercontent.com` | GitHub raw files | yes |
| `api-fxpractice.oanda.com` | OANDA practice API | no |
| `help.oanda.com` | OANDA docs | no, DNS fails |
| `candle-data.fxcorporate.com` | FXCM M1 candles | no |
| `datafeed.dukascopy.com` | Dukascopy ticks | no |

So exactly one real data source is reachable from here, and it is reachable
because it is hosted on GitHub rather than because it is a market data
service. **For twelve days this project recorded itself as blocked on broker
credentials. That was wrong.** The council session on 2026-10-12 caught it:
nobody had checked whether the data was obtainable without the owner at all.
See `docs/council/council-transcript-2026-10-12.md`.

## Source 1: the GitHub M15 mirror

`ejtraderLabs/historical-data` on GitHub, read with `ict ingest --source
mirror`. Twelve symbols at m15, m30, h1, h4 and d1. The reader takes a URL, so
reproducing the store below is one command with no download step:

```bash
ict ingest \
  https://raw.githubusercontent.com/ejtraderLabs/historical-data/main/EURUSD/EURUSDm15.csv \
  --source mirror --out data/EURUSD_M15_mirror.parquet
```

The Parquet file itself is **not** committed. The mirror states no licence, so
redistributing it from this repository would be claiming a right nobody has
established. The command above rebuilds it in about a minute.

The same reader parses any MetaTrader CSV export with a
`Date,open,high,low,close,tick_volume` header, which is what a broker's
"export history" button produces, so it is also the route for data the owner
fetches himself.

EUR/USD M15, after cleaning: **178,209 candles, 2015-01-02 to 2022-03-04**.
No duplicate timestamps, no non positive prices, no inconsistent OHLC.

### Its clock, which the mirror does not state

The mirror's stamps carry no timezone and no note saying what they are. Since
every ICT concept in this project is defined in New York time, a one hour
error would move every kill zone, so the clock was established from the data
rather than assumed:

- From 2015 onwards the last bar of the week sits at Friday 23:45 all year,
  except in March and late October, where it slips to 22:45. Those are exactly
  the weeks when US and EU daylight saving are out of step, which is what you
  see if the clock follows the EU schedule while the 17:00 New York close does
  not.
- The week opens at Monday 00:00 with no Sunday bars, and Monday 00:00 EET is
  the Sunday 22:00 UTC market open.

Both ends agree on EET in winter and EEST in summer, which is the standard
MetaTrader broker server clock. Converting on that basis puts the final bar of
the week at 16:45 New York, the bar closing at 17:00, which is the actual FX
weekly close. That is an independent confirmation rather than a restatement of
the assumption.

Before 2015 the same file closes the week at 22:45 most weeks, which is a
different clock, so the file is two series stitched together. Rather than
guess the earlier offset, everything before 2015-01-01 is dropped.

### What is wrong with it

These are limitations of the result, not caveats to be skipped over.

1. **Provenance is unverified.** The mirror states no upstream source and no
   licence. The `tick_volume` column and the broker server clock say it is a
   MetaTrader export from an unnamed retail broker. It is therefore one
   broker's view of EUR/USD, not a consolidated feed, and not the OANDA feed
   the live path would trade on.
2. **M15 is the finest granularity.** The project was designed on 1 minute
   candles. No reachable host serves M1: FXCM's own M1 archive is on a blocked
   domain. This is not a cosmetic limitation. See below.
3. **It ends 2022-03-04.** No recent regime, and nothing after the 2022
   inflation cycle began in earnest.
4. **No bid and ask.** Only one price series, so the spread must be modelled
   rather than measured. The cost model already does this, but a measured
   spread would be better and the live path has one.
5. **Tick volume, not real volume.** Normal for FX and fine for relative
   comparisons, meaningless as a size.

### What M15 granularity costs

With M15 as the base series, a model whose setup lives inside a one hour
window has four base candles to work with. Running all seven models over
2015 to 2017:

- `silver_bullet` found **zero** setups in three years. Its sweep, its
  displacement, its gap and its entry all have to fit in the 10:00 to 11:00
  New York window, and four candles cannot carry that sequence. This is a
  property of the data, not a verdict on the model.
- `mentorship_2022` found 19, which is too few to conclude anything from.
- `optimal_trade_entry` found 99, which is a workable sample.

So the mirror can test the models that read structure at M15 and above, and
cannot test the ones that need minute precision. Any model reported as
untested on this source is untested, not rejected.

## Source 2: OANDA, still not connected

`src/ict/data/oanda.py` and `ict fetch` are built and tested and need
`OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID` and `OANDA_ENVIRONMENT`. This is the
only route to M1 data, to measured bid and ask spreads, to anything after
March 2022, and to gates 5 and 6, which are paper and live trading and cannot
be done from an archive at all.

It needs two things only the owner can do, in the environment settings panel:
add those three variables, and allow `api-fxpractice.oanda.com` and
`stream-fxpractice.oanda.com`. Nothing goes in the repository.

One thing worth checking before spending time on it: whether an OANDA account
can be opened from Botswana at all. The official region selector lists
Botswana under its Africa, Middle East and India region, but OANDA Global
Markets' own eligible countries page reportedly does not, and OANDA holds no
Botswana licence. That page is on a blocked domain so it could not be checked
from here. If the answer is no, the alternative is any broker offering a
MetaTrader demo, since the mirror reader already parses that export format.

## Why the mirror is not enough on its own

It is one broker's M15 history, ending in 2022, with no stated provenance. A
result from it is real in the sense that it is real market data rather than a
random walk, which is a genuine improvement on everything this project
reported before 2026-10-12. It is not sufficient for a claim about an edge,
because a single undocumented broker feed at one granularity over seven years
is one sample of one. Gate 4 exists to probe that, and gates 5 and 6 exist
because an archive cannot tell you what your own fills look like.
