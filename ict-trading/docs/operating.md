# Operating the system day to day

The daily loop from the record, the journal that records what it did, and the
alerts that mean hands off is not the same as blind.

## The daily plan

Run before Asia opens, around 19:30 New York.

```bash
ict plan data/processed/eurusd_m1.parquet --calendar calendar.csv --account
ict plan data/processed/eurusd_m1.parquet --message-only --alert
```

The seven steps from the record: refresh the data, set the bias, map the path
to it, mark the levels, load the news, check the account, send the message.

It is **read only**. It places nothing and changes nothing, so it can be run at
any time, against a practice account or none at all, and the worst it can do is
print something wrong. That makes it the cheapest way to see what the system
thinks before it acts, which matters: a strategy you cannot inspect before it
trades is one you will only ever understand afterwards.

The bias is the same `draw_on_liquidity` the models use, read off the 4 hour
frame. It is deliberately not a second opinion. A plan that disagreed with the
engine would be describing a system nobody is running.

`--at` rebuilds the plan for any past moment, and it will say what it would
have said then: everything goes through the same point in time accessors the
engine uses, so a plan cannot see further than the engine could. That is a
test, not a promise.

Two things the plan is careful about:

- **A day with no calendar and a day with no releases do not read the same.**
  Both have no blackouts and they mean opposite things.
- **An open position turns the plan to no trade**, because the loop will not
  enter while one is live and a plan implying otherwise is misleading.

The one line message is the record's: `EUR_USD bias short, draw at 1.04179.
USD CPI m/m at Wed 10 Apr 08:30 New York, no entries 12:15 to 12:45 UTC`. It is
read on a phone at half past one in the morning, so everything else stays in
the full report.

## The journal

```bash
ict backtest data/processed/eurusd_m1.parquet --journal journal.csv
ict live data/processed/eurusd_m1.parquet --execute --trade-journal journal.csv
ict journal journal.csv --daily
```

The record's outsider verdict is why this exists: "AI that makes the right
decisions" sounds like every scam trading bot, and a visible, honest journal of
tested results is what would make anyone trust it.

So it **appends and never rewrites**. A run that ends badly leaves its rows
behind. A journal you can quietly correct is a marketing document.

Live rows are written **one trade at a time, as each closes**, not at the end. A
process that dies holding its results has no results, and a run that crashes at
3am must still have every trade before the crash on disk.

The rows come from **the broker, not from what the loop thinks it did**. A stop
that filled while the stream was quiet is exactly the trade worth having a
record of, and the loop's own memory would miss it.

Every row carries `source`: `backtest`, `paper` or `live`. Mixing them in one
file without saying which is which is how a paper record becomes a live claim,
and the summary says plainly when a journal contains no live trades at all.

The breakdowns are by model and by session, because "down 1.2R today" is a mood
and "down 1.2R, all of it in the London window, all from one model" is
something to act on. Trades opened outside every kill zone appear under their
own name so the rows add up: a breakdown that silently drops two thirds of a
run invites you to trust the third that is left.

It is a CSV on purpose. A file anyone can open in a spreadsheet and check
against the broker's own statement is worth more than a database only this
program can read.

## Alerts

```bash
export ICT_ALERT_WEBHOOK=https://api.telegram.org/bot<token>/sendMessage
ict live data/processed/eurusd_m1.parquet --execute --alert-log alerts.log
```

Console by default, optionally a file, and a webhook when the environment has
one. Telegram, Slack, ntfy, anything that takes a JSON POST. The URL comes from
the environment because it usually contains a bot token, and a token in a
commit is a bot anyone can drive.

Two rules shape the module:

- **An alert never stops the loop.** A webhook that times out at 3am cannot
  take down a process holding a position. A sink that raises is reported once
  and then left alone, because retrying a broken webhook on every fill turns
  one outage into a loop spending its time on network timeouts instead of
  candles.
- **A halt is loud and everything else stays quiet enough to keep reading.** An
  alerting system people mute is worse than none, because it looks like
  coverage. Fills and exits are one line; halts carry the reason and what was
  done about it. The webhook sink filters below a level you set, and halts and
  errors always go through regardless.

## A day, end to end

```bash
# 19:30 New York, before Asia
ict plan data/processed/eurusd_m1.parquet --calendar week.csv --account --alert

# then leave it running
ict live data/processed/eurusd_m1.parquet \
    --calendar week.csv --execute \
    --trade-journal journal.csv --alert-log alerts.log

# after the New York session
ict journal journal.csv --since 2026-01-01 --daily
```

On a VPS, that middle command is a systemd service that restarts the process
but **not the halt**. A halt is final and needs a person: the loop stopped
because it had lost track of something, and restarting it into the same market
is how a bad day becomes a bad week.

## Where this sits

None of this changes the gate order in `docs/live.md`. The plan, the journal
and the alerts are how you operate a strategy once it has earned the right to
run, and nothing here has earned it yet. Gate 1, the hand labelling, is still
unstarted and still the only thing on the critical path.

What these are good for today is running the plan against generated data to see
the shape of the output, and having the journal ready so that the first real
paper trade is recorded from the first minute rather than from whenever
somebody remembers to turn it on.
