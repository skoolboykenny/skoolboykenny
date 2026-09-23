# The dashboard

```bash
ict dashboard --journal journal.csv --out dashboard.html
```

One self contained page, about 30KB, that works offline and can be emailed.

## What it is for

The record gives it two jobs: the operator's view of the journal, and the
portfolio showcase. Those pull the same way, which is lucky, because the
honest version is also the one worth showing. The record's own outsider verdict
is why: *"AI that makes the right decisions" sounds like every scam trading
bot. A visible, honest journal of tested results is what would make anyone
trust it.*

So the page leads with the **validation gates**, not with a profit number, and
every figure says whether it came from a backtest, paper trading or live money.
A dashboard that opens with an equity curve and buries the fact that no
detector has been verified is the genre this project is trying not to be in.

While there is no live money in the journal, a banner at the top says so in
plain words. Leave it there. It is the reason the page is worth showing
anyone, and removing it is the single change that would turn this from a
research record into the thing it is trying not to resemble.

## What is on it

**Validation gates.** All six, with state and what is blocking each. No gate is
ever marked passed by the absence of a failure; it takes evidence.

**Headline tiles.** Trades, total R, expectancy, win rate, profit factor,
maximum drawdown. Drawdown is measured peak to trough, so a run that went up
and came back shows it even if it ends in profit.

**Cumulative R.** One series, so the caption names it and there is no legend
box to decode. It starts at zero rather than at the first result, because a
curve that begins at its first trade hides that trade. Hovering gives a
crosshair and the exact value.

**R per New York day.** Blue above the line, red below: that is polarity around
zero rather than identity, so it uses the diverging pair rather than two
arbitrary series colours. Each bar carries a native tooltip, so it works with
scripting off.

**By model and by session.** Horizontal bars with the value written next to
each row. One hue, because the row labels already carry identity and a
categorical ramp would imply a meaning the rows do not have. Trades opened
outside every kill zone appear under their own name so the rows add up to the
total.

**The journal table.** The most recent sixty trades. It is also the table view
that every chart on the page needs, so nothing is conveyed by colour alone.

Colours are the validated diverging pair, chosen for both light and dark:
worst adjacent colour-vision separation 21.6 light and 19.2 dark against a
floor of 8, and normal vision 32.3 and 29.0 against a floor of 15. Dark mode is
its own set of steps rather than an inversion, and it follows both the system
setting and an explicit theme attribute.

## The kill switch is not on this page

The record asks for a kill switch in the dashboard. It cannot be there, and
this is the one place the implementation deliberately departs from the spec.

This page is a static file whose entire purpose is being sent to people. A
button that flattens an OANDA account needs a trading token, which would mean
a live credential sitting inside a file you are handing out. No amount of care
makes that acceptable.

```bash
ict flatten                 # asks first
ict flatten --yes           # for a script
```

It cancels every resting order and closes every open position at market, names
the environment before it does anything, and sends a halt alert afterwards. The
token is already in the environment and the confirmation is a person rather
than a click. The dashboard's footer says where to find it.

## Why hand built SVG

No plotting library. The page stays small enough to email, needs no network,
and every mark follows one spec: 2px lines, 4px rounded ends on the data end of
a bar and square on the baseline, a 2px gap between adjacent bars, recessive
grid and axes, text in text colours rather than series colours.

A charting library would have been faster to write and would have produced a
page that looks like every other charting library.

## When there is nothing to show

The page renders with no journal at all: you get the gates, the blockers, and
nothing else. That is the correct output for where this project currently
stands, and it is worth generating once now so the shape is familiar before
there is anything real on it.
