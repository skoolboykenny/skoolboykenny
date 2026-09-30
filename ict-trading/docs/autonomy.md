# Running this without a person

`ict advance` looks at what is on disk, works out which gate is next, and
either runs it or says who is blocking.

```bash
ict advance          # report only
ict advance --run    # run the next step if it is a machine's to run
```

Exit codes, because a scheduled run reads them:

| Code | Meaning |
| --- | --- |
| 0 | Something was advanced, or a dry run reported cleanly |
| 1 | A gate ran and did not pass. That is a result, not an error |
| 2 | Blocked on a person |
| 3 | Gates 1 to 4 have passed; paper trading starts when you start it |

## What it will not do

These are the boundaries that make it safe to run unattended, and each is
enforced in code rather than by intention.

**It never places an order.** `live` and `flatten` are not on the allow list,
and `run_step` refuses any command that is not on it. That list is the
boundary, not a convenience: it is what stops a later edit or a mistake from
turning this into something that can trade.

**It never adjusts anything to make a gate pass.** This is the real risk of
running unattended. An agent optimising for a green gate rather than for the
truth would tune thresholds until `ict verify` agreed with itself, and the
result would look like validation while being its opposite. So `advance` runs
gates and reports them. Changing a threshold because a gate failed is a
decision for a person looking at hand labels, and there is deliberately no code
path here that does it. A test asserts no step carries a tuning flag.

**It never skips a gate.** The order in the project record is the order here,
and a gate that has *failed* is not a gate that has passed: it blocks
everything after it until someone deals with it.

## What it cannot do, and why it is not a capability limit

**Gate 1, the hand labelling.** An agent could mark 600 charts. The number
would be worthless.

The detectors were written from ICT's definitions. An agent labelling the
charts reads those same definitions and marks what they imply, so it agrees
with the code almost everywhere by construction, and the 90% measures nothing
except internal consistency. The gate exists to catch exactly one failure: the
code's idea of a sweep having drifted from a trader's. An agent is on the
code's side of that comparison and cannot be the independent check on it.

There is a second reason. The person who will trade this is the one whose
reading has to match. If the detectors agree with an agent but not with you,
you will override them in the moment, and the system stops being the thing that
was tested.

**Opening the broker account.** Identity and terms need a person, and legally
it has to be the account holder.

**Starting paper trading, and going live.** Both are decisions to expose
something, and the second exposes money. The project's own architecture already
says this: the AI review layer may only shrink or cancel a trade, the risk
limits are code the AI cannot override, and a halt is final and needs a person.

## Setting it up

Two changes in the cloud environment's settings.

**Credentials.** Add `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID` and
`OANDA_ENVIRONMENT=practice` as environment variables. Never paste a token into
a chat. A new session picks them up.

**Network.** The policy denies market data hosts by default, which is why
`ict fetch` has never run. Allow `api-fxpractice.oanda.com` and
`stream-fxpractice.oanda.com`, or choose a broader access level.

With both in place, `ict advance --run` on a schedule will fetch the history,
then stop at gate 1 and wait for you. Once you have labelled, it will score the
labels, run the in sample backtest, the walk forward and the robustness
harness, and stop again at paper trading.

## What a scheduled run should do with each exit code

- **0** — carry on; run again to take the next step.
- **1** — stop and report. A failed gate is information, and the next move is a
  person deciding whether the detectors or the expectations were wrong.
- **2** — report once and go quiet. Repeating "still blocked on you" every hour
  is nagging, not monitoring.
- **3** — report that everything a machine can check has been checked.

The honest expectation is that this reaches gate 3 or 4 and stops with a
failure, six to eight weeks after real data lands. That is the system working.
