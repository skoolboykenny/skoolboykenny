# Data

The 1 minute candle data every later phase depends on. This step runs before
the detectors: there is nothing to verify detectors against until it has.

## Source

[Dukascopy Bank](https://www.dukascopy.com/) historical feed, via the
[`dukascopy-node`](https://github.com/Leo4815162342/dukascopy-node) CLI. It is
free, needs no account, and publishes tick data back to 2003, which the CLI
aggregates into the timeframe asked for.

| Setting | Value |
| --- | --- |
| Instruments | EURUSD, GBPUSD |
| Timeframe | m1 (1 minute) |
| Price types | bid and ask, downloaded separately |
| Range | 2021-01-01 to today |
| Timestamps | UTC, epoch milliseconds in the raw CSV |
| Volumes | included |

Bid and ask are fetched separately because the feed serves them separately.
They are joined on the minute in the build step, which is where the mid prices
and the spread come from. The spread matters: a backtest that fills at the mid
price and ignores it will report an edge that does not survive contact with a
broker.

## Layout

```
data/
  raw/                              one CSV per instrument, side and month
    eurusd/bid/eurusd-m1-bid-2021-01-01-2021-02-01.csv
    eurusd/ask/...
    gbpusd/...
  processed/
    eurusd_m1.parquet               the merged result
    gbpusd_m1.parquet
    summary.json                    the numbers in the table below
```

`data/` is in `.gitignore`. The files are large and reproducible from the two
commands below, and Dukascopy's data is theirs to license, not mine to
redistribute.

## Columns in the processed files

| Column | Meaning |
| --- | --- |
| `timestamp_utc` | Index. UTC, minute resolution |
| `bid_open` `bid_high` `bid_low` `bid_close` | Bid side |
| `ask_open` `ask_high` `ask_low` `ask_close` | Ask side |
| `mid_open` `mid_high` `mid_low` `mid_close` | `(bid + ask) / 2` |
| `spread` | `ask_close - bid_close` |
| `volume` | Bid volume plus ask volume |

Only minutes quoted on **both** sides are kept. A minute with one side missing
has no mid price and no spread, and carrying it half empty would push that
decision into every consumer downstream.

## How to rerun

```bash
cd ict-trading

# One month of every instrument and price type, to check the feed is reachable
python scripts/download_data.py --months 1

# The full range. Resumable: re-running skips chunks already on disk
python scripts/download_data.py

# Merge the chunks and refresh the table below
python scripts/build_parquet.py
```

The download is chunked by month, so a failure costs one month rather than the
whole range. Failed chunks are listed at the end of the run, and re-running the
script retries only those. Each chunk is attempted three times, and the CLI
retries individual artifacts within a chunk as well.

A chunk counts as downloaded only if its file exists **and has bytes in it**.
`dukascopy-node` prints `File saved` and writes a zero byte file when it cannot
reach the data feed, so treating a successful exit code as success would
silently produce an empty dataset.

### If the download produces empty files

Check the feed is reachable before assuming the script is at fault:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  "https://datafeed.dukascopy.com/datafeed/EURUSD/2021/00/04/10h_ticks.bi5"
```

A `200` means the feed is fine. A connection or proxy error means the network
is blocking `datafeed.dukascopy.com`, which some corporate networks and
sandboxed environments do. The download must be run somewhere with access to
it.

## Reading the processed files

The detectors read these directly. They run on the mid price by default, with
the other two sides available:

```bash
ict plot data/processed/eurusd_m1.parquet --date 2024-03-14
ict plot data/processed/eurusd_m1.parquet --date 2024-03-14 --side bid
```

The `spread` column is carried through rather than dropped, so a later phase
can refuse to trade a minute where the spread was wider than normal.

## Gaps

`build_parquet.py` reports every gap longer than five minutes that is not the
weekend close, so what remains is either a market holiday or a hole in the
download. Gaps are reported, never filled: a missing minute is information, and
inventing candles would give the detectors structure that never traded.

The weekend is taken as Friday 20:00 UTC to Sunday 22:00 UTC. That is wider
than the true close on both sides, because the 17:00 New York boundary moves an
hour with daylight saving. The cost is that a real hole falling inside that
band would not be reported; the alternative was reporting a gap every single
week.

Expect a handful of genuine gaps over a multi-year range: Christmas Day, New
Year's Day and Good Friday are the usual ones.

## Summary

<!-- SUMMARY:START -->

Not yet populated. Run `python scripts/build_parquet.py` and this table is
rewritten in place with the row count, date range and gap count per instrument.

<!-- SUMMARY:END -->
