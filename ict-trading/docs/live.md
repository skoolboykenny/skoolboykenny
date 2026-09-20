# Getting to real time trading

This document is the path from where the project is to a live account, and the
order matters. Every step exists because skipping it is how people lose money
slowly and then quickly.

## Where the project is

Your record sets six gates. Nothing advances until the one before it passes.

| Gate | State |
| --- | --- |
| 1. Detectors agree with hand labels 90% of the time | Not started. Tooling exists, labelling is manual |
| 2. Three years of 1 minute data, in sample, with costs | Blocked until data lands |
| 3. Walk forward, out of sample only | Machinery built, run only on generated data |
| 4. Robustness: parameter sensitivity and Monte Carlo | Built (`ict robustness`), never run on real data |
| 5. Paper trading, 3 months or 100 trades | Built (`ict live`), never run |
| 6. Small live, 3 months at minimum size | Gated on all of the above |

Gates 5 and 6 are what "real time trading" means. The realistic timeline is six
to nine months, and the honest expectation is that the project stops at gate 2,
3 or 4, because that is where most strategies stop.

## Step 1: an OANDA practice account

One integration solves the data problem and the execution problem together.

1. Open a practice account at oanda.com. It is free and needs no deposit.
2. In the account, go to **Manage API Access** and generate a token.
3. Export the credentials. **They never go in this repository.**

```bash
export OANDA_API_TOKEN=your-token-here
export OANDA_ACCOUNT_ID=101-004-12345678-001
export OANDA_ENVIRONMENT=practice
```

Put those in your shell profile or a `.env` file that is git ignored. If a
token ever reaches a commit, revoke it in the OANDA dashboard immediately;
rewriting history does not un-leak it.

The practice and live environments differ only by hostname and token, so every
step up to and including gate 5 runs with no money at risk.

## Step 2: real data at last

```bash
ict fetch --instrument EUR_USD --start 2021-01-01 --out data/processed/eurusd_m1.parquet
ict gaps data/processed/eurusd_m1.parquet
```

`ict fetch` pages through OANDA's candles endpoint, which caps a response at
5,000 candles, so five years of 1 minute data is a few thousand requests and
takes a while. It writes one Parquet chunk per month, so an interrupted
download resumes rather than starting again, and re-downloads only the final
month, which may have been written before that month finished.

Bid and ask are downloaded together, never the mid alone. The spread decides
whether a minute was tradeable, and it widens exactly when these setups fire.
The stored layout is the one `read_parquet` already understands, so everything
downstream works unchanged.

Incomplete candles are dropped on the way in. A candle still forming has a high
and a low that are not final, and treating one as closed is the same lookahead
bug the timeframe stack exists to prevent.

Then check `ict gaps`. Weekend closes dominate the top of that list, which is
expected. Anything large that is not a weekend is a data problem worth knowing
about before a detector runs over it.

## Step 3: the labelling, which is gate 1

```bash
ict sample data/processed/eurusd_m1.parquet --concept sweep --count 100 --out labels/sweeps
# mark labels.csv by hand, then
ict verify labels/sweeps
```

This is the step nobody can do for you, and it is the one that decides whether
any of the rest means anything. The charts are exported without the detector's
answers on them, deliberately: a chart showing what the code thinks anchors you
to it, and the score comes out inflated.

Expect failures. The MSS prominence setting is already flagged in `config.py`
as the least certain in the project. Tune against the labels, not against
backtest results.

**Do not proceed to gate 2 until `ict verify` passes at 90%.** A profitable
backtest built on detectors that disagree with you is evidence about the code,
not about the market.

## Step 4: gates 2, 3 and 4

```bash
ict backtest data/processed/eurusd_m1.parquet --from 2021-01-01 --to 2023-12-31
ict rank data/processed/eurusd_m1.parquet --train-days 365 --test-days 90
ict robustness data/processed/eurusd_m1.parquet --model silver_bullet
```

`ict robustness` is gate 4 and answers two questions the other two cannot.

**Parameter sensitivity.** It moves one setting at a time, one step either
side, and reports the share of neighbours that stayed profitable. A real edge
degrades gently. One that exists at the baseline and nowhere near it was fitted
to the sample. It moves one field at a time on purpose: crossing every field is
a parameter search wearing a robustness test's clothes.

**Monte Carlo.** It reshuffles the trades a few thousand times, because trade
order decides the drawdown and trade order is luck. The observed drawdown is
one draw from that distribution. Size positions off the 95th percentile, not
off what happened to occur. It also resamples with replacement to put a
confidence interval on expectancy, which answers the question the headline
number cannot: could this have been zero? An interval spanning zero means the
edge is not established, whatever the total says.

The command exits non-zero unless both halves pass, so it can gate a build.

## Step 5: paper trading, which is gate 5

```bash
# Watch it decide, without sending anything
ict live data/processed/eurusd_m1.parquet --model silver_bullet

# Once the log looks right, trade the practice account
ict live data/processed/eurusd_m1.parquet --model silver_bullet --execute
```

It is a dry run unless `--execute` is passed. In dry run it logs every setup it
would have placed and sends nothing, which is how you check that the live path
sees what the backtest saw before it can cost anything.

What the loop does:

- **Only closed candles count.** The forming minute is held back, always. This
  is the lookahead rule at the place it is easiest to break, because live the
  forming candle is right there.
- **The same code decides.** Same detectors, same models, same risk manager as
  the backtest. Paper trading a re-implementation measures the
  re-implementation.
- **Every order carries its own stop and target**, attached at fill time in the
  same request. A position is never naked, not even for the milliseconds
  between a fill and a follow up call. If the process dies the instant after a
  fill, the broker still holds the stop.
- **Orders expire with their window.** A Silver Bullet entry filled at
  lunchtime is a different strategy wearing the name.
- **The account is the truth.** Before every decision the loop asks the broker
  for its equity and positions rather than trusting its own memory. A stop that
  filled while the stream was quiet is still a stop that filled.
- **A halt is final.** Connection loss, a stream gone quiet for thirty seconds,
  drawdown past the guard, or a run of losses, and it cancels everything,
  closes everything, and stops. It does not restart itself. A loop that trades
  through its own kill switch does not have one.

Set `--max-drawdown` from the worst drawdown the backtest saw, not from what
feels tolerable.

Run it for three months or 100 trades. Then compare: if the live results sit
outside the range the backtest predicted, the backtest was wrong, and finding
that out on a practice account is the cheapest possible outcome.

For it to run unattended, put it on a small VPS in London or New York, close to
the broker, as a systemd service that restarts the process but not the halt.

## Step 6: small live

Change one environment variable:

```bash
export OANDA_ENVIRONMENT=live
ict live ... --execute --i-understand
```

The extra flag is required against the live environment and is there to make
this a decision rather than a typo.

Minimum position size for three months. Not the size the backtest justifies,
the smallest size the broker allows. The question at this stage is whether the
system behaves as expected with real fills, real slippage and real spread
widening, and that question is answered just as well with tiny size.

## What can still go wrong after gate 6

- **Spread and slippage on news.** The backtest models both, but a practice
  account fills better than a live one and neither matches a real spike.
- **The strategy stopping working.** Edges decay. The halt conditions exist
  because the system cannot tell decay from a bad run, and neither can you in
  the moment.
- **You.** The largest risk in the project is overriding it by hand after a run
  of losses. The rules are only worth something if they are the ones that
  execute.

Leveraged trading carries a high risk of loss. Nothing in this repository is
financial advice, and the gates above are the minimum, not a guarantee.
