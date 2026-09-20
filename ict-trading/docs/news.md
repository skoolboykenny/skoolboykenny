# The news module and the AI review layer

Two things that can stop a trade. Neither can start one.

## The news gate

From the record: no ICT entry from fifteen minutes before a high impact
release to fifteen minutes after it. This is a risk check, which the record
puts in the category of things code enforces and nothing overrides, so it lives
outside the models rather than inside them where a model could forget it.

The gate blocks **entries, never exits**. A position already open when CPI
lands keeps its stop and target with the broker. Pulling them because of a
calendar entry is how a small loss becomes an unbounded one.

### Getting a calendar

Forex Factory is the source the record names. It has no official API and its
terms restrict scraping, so the module reads files and never fetches:

- **Live.** The weekly calendar export from the Forex Factory site.
- **Backtests.** A licensed or open historical calendar. You need several
  years, with actual, forecast and previous per event, or gate 2 runs
  ungated and the result is not comparable with a live one.

Any CSV works as long as it has a date, and columns are matched by alias
because no two exports agree on names. Impact is normalised from the several
ways calendars say it (`High`, `3`, `red`, `High Impact Expected`).

**Set the timezone.** `--calendar-timezone` is the zone the *file* is in, and
Forex Factory exports in whatever the account is set to. Getting it wrong
shifts every window by hours with no error at all.

```bash
ict news calendar.csv --parquet data/processed/eurusd_m1.parquet
```

That prints what the gate would block before it blocks anything, including the
share of candles it covers. Watch that number. A gate blocking a fifth of the
session is not a filter, it is a different strategy, and results stop being
comparable with an ungated run.

```bash
ict backtest data/processed/eurusd_m1.parquet --calendar calendar.csv
ict live data/processed/eurusd_m1.parquet --calendar calendar.csv
```

FOMC is flagged separately rather than blocking its whole day. `--block-fomc-day`
turns that on, and it is off by default because blocking a whole day is a large
claim to make on behalf of a strategy nobody has tested through one.

**No calendar means nothing is gated.** That is not the same as a quiet week,
and every report says so rather than letting an ungated run look gated.

## The news playbooks

Two strategies, from the record, kept apart from the ICT models so each is
tested on its own record. They are deliberately absent from the ICT model
registry so they can never drift into a ranking.

**Directional.** The expected direction is the sign of forecast minus previous.
After the release, the surprise confirms or cancels it, and entry needs the
first 1 minute candle to close in the surprise's direction.

**Spike correction.** After a spike larger than K times the pre-release ATR,
wait for it to stall, then fade toward its 50% level. The spike is treated as a
liquidity sweep, so entry needs a market structure shift and a return into the
gap the spike left.

Surprises are **scaled by each event's own history**, and that is not cosmetic.
A CPI miss of 0.1 and an NFP miss of 0.1 are not the same event: payrolls are
quoted in thousands and inflation in percent, so an unscaled surprise ranks
every payroll release above every inflation release regardless of what the
market did. An event with fewer than a handful of past releases gets no scale
at all rather than one estimated from three observations.

**Costs here are not the costs elsewhere.** `NewsCostModel` widens the spread
to three to five times normal for the first sixty seconds, decaying back. A
news backtest run at normal spread is testing a market that does not exist at
08:30, and any result produced without it should be thrown away.

## The AI review layer

The record: the layer "receives structured data, not a raw chart", answers
take, skip or reduce with a written reason, and "can only make a trade smaller
or cancel it, never larger or earlier".

That last constraint is enforced in the `Verdict` type, not in the prompt. A
verdict asking for triple size is clamped to 1. An action nobody recognises
becomes a skip. A reply that cannot be parsed becomes a take, because a parsing
failure is the reviewer's fault and the strategy should not pay for it.

**Why the type and not the prompt.** Headlines are untrusted text from the
internet going into a language model, so anything in them that reads like an
instruction is a possible injection. The clamp means the worst a successful
injection can do is skip a trade the strategy wanted, which is a bad day rather
than a blown account. A prompt is not a boundary.

Three reviewers:

- `off` (default). No layer.
- `rules`. Deterministic checks with no API and no key: a release inside the
  trade's expected life, a reward to risk below the floor, a losing streak,
  trading against the daily bias. Every rule can be stated in a sentence and
  argued with, which is more than can be said for a paragraph of generated
  prose.
- `claude`. Sends the structured request to the Anthropic API. Needs
  `ANTHROPIC_API_KEY` in the environment. An API error, a timeout or an
  unparseable answer produces a take, so the layer breaking never becomes a
  source of missed trades.

```bash
ict backtest data/processed/eurusd_m1.parquet \
    --review rules --review-journal decisions.csv
ict review-audit decisions.csv
```

## The audit, which is the part that matters

From the record: "Every decision, including skipped ones, is logged. If skipped
trades would have won more than they lost, the AI layer is switched off."

That sentence is the only thing between a review layer and an expensive
superstition. A filter feels useful because the losers it blocked are memorable
and the winners it blocked are invisible.

So the engine runs a **shadow broker**: every reviewed setup is also placed in a
parallel simulation that ignores the verdict, and when it resolves the R is
attached to the decision. Without it `skipped_r` is always zero and
`should_switch_off` can never become true, which makes the record's rule a
comment rather than a check.

The shadow carries **its own risk manager**, and that is not a detail. Blocking
a trade means the loss never happens, so "one loss per session" never trips and
the strategy goes on to see setups it would never have reached. Counting all of
them made a block-everything layer look ten times better than it was: −277R
against an unreviewed run's −26R on the same forty days.

Two limitations to keep in mind:

- Both brokers hold one position at a time, so a counterfactual that would have
  overlapped a later real trade is not simulated. That understates the layer's
  effect rather than overstating it.
- The counterfactual is an estimate from the same engine with the same
  pessimism. Take the sign, not the decimal place. A layer giving up +8R of
  winners is wrong whatever the third significant figure says.

`ict review-audit` exits non-zero when the layer should come off, so it can gate
a build. It refuses to give a verdict below twenty blocked trades: a layer that
skipped three has not been tested, whichever way those three went.

## Where this sits in the gates

Nothing here changes the order in `docs/live.md`. The gate and the layer are
filters on a strategy that has not yet passed gate 1, and a filter on an
unverified strategy is a filter on a bug. Build them now, run them after the
labelling.

The honest default for the review layer is `off` until its own audit says
otherwise, on real data, over at least twenty blocked trades.
