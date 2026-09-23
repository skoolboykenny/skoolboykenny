"""The dashboard: what the system did, in one page you can send someone.

The record gives this two jobs. It is the operator's view of the journal and
the annotated charts, and it doubles as the portfolio showcase, because "a
visible, honest journal of tested results is what would make anyone trust it".

Those two jobs pull the same way, which is lucky: the honest version is also
the one worth showing. So the page leads with the gates rather than with a
profit number, and every figure says whether it came from a backtest, paper
trading or live money. A dashboard that opens with an equity curve and buries
the fact that no detector has been verified is the genre this project is
trying not to be in.

**The kill switch is deliberately not here.** The record asks for one in the
dashboard, and it cannot be: this page is a static file meant to be sent to
people, and a button that flattens an OANDA account needs a token, which would
mean a live trading credential inside a file whose whole purpose is being
shared. `ict flatten` does the same job from the command line, where the token
is already in the environment and the confirmation prompt is a person rather
than a click.

Charts are hand built SVG rather than a plotting library. The page stays small
enough to email, works with no network, and the marks follow one spec.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import MARKET_TZ
from .journal import daily_breakdown, read_journal
from .verification import PASS_THRESHOLD

#: Palette roles, light and dark. Validated: worst adjacent CVD delta E 21.6
#: light and 19.2 dark, normal vision 32.3 and 29.0, all well clear of the
#: floors. Blue and red are the diverging pair, used for R above and below
#: zero, which is polarity rather than identity.
PALETTE = {
    "light": {
        "surface": "#fcfcfb",
        "panel": "#ffffff",
        "ink": "#0b0b0b",
        "ink2": "#52514e",
        "muted": "#898781",
        "axis": "#c3c2b7",
        "pos": "#2a78d6",
        "neg": "#e34948",
        "mid": "#f0efec",
        "good": "#0ca30c",
        "warning": "#fab219",
        "critical": "#d03b3b",
    },
    "dark": {
        "surface": "#1a1a19",
        "panel": "#232322",
        "ink": "#ffffff",
        "ink2": "#c3c2b7",
        "muted": "#898781",
        "axis": "#383835",
        "pos": "#3987e5",
        "neg": "#e66767",
        "mid": "#383835",
        "good": "#0ca30c",
        "warning": "#fab219",
        "critical": "#d03b3b",
    },
}

#: The six gates from the record, in order.
GATES = (
    ("Detectors agree with hand labels 90%", "gate1"),
    ("In sample backtest with costs", "gate2"),
    ("Walk forward, out of sample only", "gate3"),
    ("Robustness: sensitivity and Monte Carlo", "gate4"),
    ("Paper trading, 3 months or 100 trades", "gate5"),
    ("Small live, 3 months", "gate6"),
)


@dataclass
class Gate:
    """One gate, where it stands, and what it would take to move it."""

    name: str
    state: str = "not started"  # passed, failed, running, not started
    detail: str = ""
    #: What the gate is actually asking for, in a sentence.
    what: str = ""
    #: The commands, in order. Each is (description, command or "").
    steps: tuple[tuple[str, str], ...] = ()
    #: What "done" looks like, so the gate is not a matter of opinion.
    done_when: str = ""
    #: True when this is the gate to work on now, so the page can open it.
    next_up: bool = False

    @property
    def status(self) -> str:
        return {
            "passed": "good",
            "failed": "critical",
            "running": "warning",
        }.get(self.state, "muted")

    @property
    def has_body(self) -> bool:
        return bool(self.what or self.steps or self.done_when)


@dataclass
class Dashboard:
    """Everything the page draws."""

    title: str = "ICT trading system"
    journal: pd.DataFrame = field(default_factory=pd.DataFrame)
    gates: list[Gate] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    generated_at: pd.Timestamp = field(
        default_factory=lambda: pd.Timestamp.now(tz="UTC")
    )
    charts: list[dict] = field(default_factory=list)

    @property
    def has_live(self) -> bool:
        return "live" in self.sources


def _money(value: float) -> str:
    return f"{value:+,.2f}"


def _pct(value: float) -> str:
    return f"{value:.1%}" if value == value else "—"


def summarise(frame: pd.DataFrame) -> dict:
    """The headline numbers, computed once for tiles and prose alike."""
    if frame.empty:
        return {"trades": 0}

    wins = frame.loc[frame["net"] > 0]
    losses = frame.loc[frame["net"] <= 0]
    total_r = float(frame["r_multiple"].sum())
    gross_win = float(wins["net"].sum())
    gross_loss = abs(float(losses["net"].sum()))

    equity = frame.sort_values("closed_at")["net"].cumsum()
    peak = equity.cummax().clip(lower=0)
    base = 10_000.0
    curve = base + equity
    peaks = (base + peak).clip(lower=base)
    drawdown = float(((peaks - curve) / peaks).max()) if len(curve) else 0.0

    return {
        "trades": len(frame),
        "total_r": total_r,
        "expectancy_r": total_r / len(frame),
        "win_rate": len(wins) / len(frame),
        "profit_factor": gross_win / gross_loss if gross_loss else float("inf"),
        "net": float(frame["net"].sum()),
        "costs": float(frame["costs"].sum()),
        "max_drawdown": drawdown,
        "first": frame["closed_at"].min(),
        "last": frame["closed_at"].max(),
    }


# --- charts -----------------------------------------------------------------


def equity_svg(frame: pd.DataFrame, width: int = 760, height: int = 240) -> str:
    """Cumulative R over time. One series, so the title names it and there is
    no legend box to read."""
    if frame.empty:
        return _empty_chart(width, height, "No trades yet")

    ordered = frame.sort_values("closed_at")
    values = ordered["r_multiple"].cumsum().tolist()
    stamps = ordered["closed_at"].tolist()
    points = [0.0] + values

    pad = {"l": 48, "r": 16, "t": 12, "b": 26}
    plot_w = width - pad["l"] - pad["r"]
    plot_h = height - pad["t"] - pad["b"]

    lo, hi = min(points), max(points)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    lo -= span * 0.08
    hi += span * 0.08

    def x_of(i: int) -> float:
        return pad["l"] + (plot_w * i / max(len(points) - 1, 1))

    def y_of(v: float) -> float:
        return pad["t"] + plot_h * (1 - (v - lo) / (hi - lo))

    line = " ".join(
        f"{'M' if i == 0 else 'L'}{x_of(i):.1f},{y_of(v):.1f}"
        for i, v in enumerate(points)
    )
    area = (
        f"M{x_of(0):.1f},{y_of(0):.1f} "
        + " ".join(f"L{x_of(i):.1f},{y_of(v):.1f}" for i, v in enumerate(points))
        + f" L{x_of(len(points) - 1):.1f},{y_of(lo):.1f} L{x_of(0):.1f},{y_of(lo):.1f} Z"
    )

    zero_y = y_of(0.0) if lo <= 0 <= hi else None
    grid = []
    for step in range(4):
        v = lo + (hi - lo) * step / 3
        y = y_of(v)
        grid.append(
            f'<line class="grid" x1="{pad["l"]}" y1="{y:.1f}" '
            f'x2="{width - pad["r"]}" y2="{y:.1f}"/>'
            f'<text class="tick" x="{pad["l"] - 8}" y="{y + 4:.1f}" '
            f'text-anchor="end">{v:+.1f}</text>'
        )

    hover = json.dumps(
        [
            {
                "x": round(x_of(i + 1), 1),
                "y": round(y_of(v), 1),
                "r": round(v, 2),
                "t": str(pd.Timestamp(stamps[i]).tz_convert(MARKET_TZ).strftime("%d %b %Y %H:%M")),
            }
            for i, v in enumerate(values)
        ]
    )

    final = values[-1]
    colour = "var(--pos)" if final >= 0 else "var(--neg)"
    return f"""<figure class="chart">
  <figcaption>Cumulative R, every journalled trade in order</figcaption>
  <svg viewBox="0 0 {width} {height}" role="img"
       aria-label="Cumulative R over time, ending at {final:+.2f}R"
       data-hover='{hover}' class="equity">
    {''.join(grid)}
    {f'<line class="zero" x1="{pad["l"]}" y1="{zero_y:.1f}" x2="{width - pad["r"]}" y2="{zero_y:.1f}"/>' if zero_y else ''}
    <path d="{area}" fill="{colour}" opacity="0.10"/>
    <path d="{line}" fill="none" stroke="{colour}" stroke-width="2"
          stroke-linejoin="round" stroke-linecap="round"/>
    <circle class="cursor" r="5" fill="{colour}" stroke="var(--panel)"
            stroke-width="2" opacity="0"/>
    <line class="crosshair" y1="{pad['t']}" y2="{height - pad['b']}" opacity="0"/>
  </svg>
  <div class="tip" hidden></div>
</figure>"""


def daily_svg(frame: pd.DataFrame, width: int = 760, height: int = 200) -> str:
    """R per New York day. Polarity around zero, so the diverging pair."""
    if frame.empty:
        return _empty_chart(width, height, "No trades yet")

    daily = daily_breakdown(frame)
    if daily.empty:
        return _empty_chart(width, height, "No trades yet")

    pad = {"l": 48, "r": 16, "t": 12, "b": 26}
    plot_w = width - pad["l"] - pad["r"]
    plot_h = height - pad["t"] - pad["b"]

    values = daily["r_multiple"].tolist()
    hi = max(max(values), 0.0)
    lo = min(min(values), 0.0)
    if hi == lo:
        hi, lo = 1.0, -1.0
    span = (hi - lo) or 1.0

    def y_of(v: float) -> float:
        return pad["t"] + plot_h * (1 - (v - lo) / span)

    zero = y_of(0.0)
    n = len(values)
    # A 2px surface gap between adjacent bars, per the mark spec.
    slot = plot_w / n
    bar_w = max(slot - 2, 1.5)
    radius = min(4.0, bar_w / 2)

    bars = []
    for i, v in enumerate(values):
        x = pad["l"] + slot * i + (slot - bar_w) / 2
        y = y_of(v)
        top, bottom = (y, zero) if v >= 0 else (zero, y)
        h = max(abs(bottom - top), 1.0)
        colour = "var(--pos)" if v >= 0 else "var(--neg)"
        # Rounded at the data end only, square on the baseline.
        r = min(radius, h)
        if v >= 0:
            path = (f"M{x:.1f},{top + h:.1f} L{x:.1f},{top + r:.1f} "
                    f"Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f} "
                    f"L{x + bar_w - r:.1f},{top:.1f} "
                    f"Q{x + bar_w:.1f},{top:.1f} {x + bar_w:.1f},{top + r:.1f} "
                    f"L{x + bar_w:.1f},{top + h:.1f} Z")
        else:
            path = (f"M{x:.1f},{top:.1f} L{x:.1f},{top + h - r:.1f} "
                    f"Q{x:.1f},{top + h:.1f} {x + r:.1f},{top + h:.1f} "
                    f"L{x + bar_w - r:.1f},{top + h:.1f} "
                    f"Q{x + bar_w:.1f},{top + h:.1f} {x + bar_w:.1f},{top + h - r:.1f} "
                    f"L{x + bar_w:.1f},{top:.1f} Z")
        label = f"{daily['date'].iloc[i]} · {v:+.2f}R · {int(daily['trades'].iloc[i])} trades"
        bars.append(
            f'<path d="{path}" fill="{colour}"><title>{html.escape(label)}</title></path>'
        )

    ticks = []
    for step in range(3):
        v = lo + span * step / 2
        y = y_of(v)
        ticks.append(
            f'<line class="grid" x1="{pad["l"]}" y1="{y:.1f}" '
            f'x2="{width - pad["r"]}" y2="{y:.1f}"/>'
            f'<text class="tick" x="{pad["l"] - 8}" y="{y + 4:.1f}" '
            f'text-anchor="end">{v:+.1f}</text>'
        )

    return f"""<figure class="chart">
  <figcaption>R per New York day. Blue above the line, red below.</figcaption>
  <svg viewBox="0 0 {width} {height}" role="img"
       aria-label="R per day, {len(values)} days">
    {''.join(ticks)}
    {''.join(bars)}
    <line class="zero" x1="{pad['l']}" y1="{zero:.1f}"
          x2="{width - pad['r']}" y2="{zero:.1f}"/>
  </svg>
</figure>"""


def breakdown_svg(
    frame: pd.DataFrame, column: str, caption: str, width: int = 760
) -> str:
    """Horizontal bars by model or session, with direct labels.

    One hue: the row labels carry identity, so colour has no job here beyond
    sign. Using a categorical ramp would imply a meaning the rows do not have.
    """
    if frame.empty or column not in frame.columns:
        return ""

    values = frame[column].fillna("").astype(str).replace(
        {"": "outside a kill zone", "nan": "outside a kill zone"}
    )
    grouped = (
        frame.assign(_k=values)
        .groupby("_k")
        .agg(r=("r_multiple", "sum"), n=("r_multiple", "size"))
        .sort_values("r")
    )
    if grouped.empty:
        return ""

    row_h = 30
    pad = {"l": 168, "r": 88, "t": 6, "b": 6}
    height = pad["t"] + pad["b"] + row_h * len(grouped)
    plot_w = width - pad["l"] - pad["r"]

    biggest = max(abs(grouped["r"].max()), abs(grouped["r"].min()), 1e-9)
    centre = pad["l"] + plot_w / 2

    rows = []
    for i, (name, row) in enumerate(grouped.iterrows()):
        y = pad["t"] + row_h * i + 6
        h = row_h - 12
        length = (abs(row["r"]) / biggest) * (plot_w / 2)
        positive = row["r"] >= 0
        x = centre if positive else centre - length
        colour = "var(--pos)" if positive else "var(--neg)"
        r = min(4.0, max(length, 0.1))
        if positive:
            path = (f"M{x:.1f},{y:.1f} L{x + max(length - r, 0):.1f},{y:.1f} "
                    f"Q{x + length:.1f},{y:.1f} {x + length:.1f},{y + r:.1f} "
                    f"L{x + length:.1f},{y + h - r:.1f} "
                    f"Q{x + length:.1f},{y + h:.1f} {x + max(length - r, 0):.1f},{y + h:.1f} "
                    f"L{x:.1f},{y + h:.1f} Z")
        else:
            path = (f"M{x + length:.1f},{y:.1f} L{x + r:.1f},{y:.1f} "
                    f"Q{x:.1f},{y:.1f} {x:.1f},{y + r:.1f} "
                    f"L{x:.1f},{y + h - r:.1f} "
                    f"Q{x:.1f},{y + h:.1f} {x + r:.1f},{y + h:.1f} "
                    f"L{x + length:.1f},{y + h:.1f} Z")

        label_x = centre + length + 10 if positive else centre - length - 10
        anchor = "start" if positive else "end"
        rows.append(
            f'<text class="rowlabel" x="{pad["l"] - 12}" y="{y + h / 2 + 4:.1f}" '
            f'text-anchor="end">{html.escape(str(name))}</text>'
            f'<path d="{path}" fill="{colour}"/>'
            f'<text class="value" x="{label_x:.1f}" y="{y + h / 2 + 4:.1f}" '
            f'text-anchor="{anchor}">{row["r"]:+.2f}R · {int(row["n"])}</text>'
        )

    return f"""<figure class="chart">
  <figcaption>{html.escape(caption)}</figcaption>
  <svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(caption)}">
    <line class="zero" x1="{centre:.1f}" y1="{pad['t']}"
          x2="{centre:.1f}" y2="{height - pad['b']}"/>
    {''.join(rows)}
  </svg>
</figure>"""


def _empty_chart(width: int, height: int, message: str) -> str:
    return f"""<figure class="chart">
  <svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(message)}">
    <text class="tick" x="{width / 2}" y="{height / 2}" text-anchor="middle">
      {html.escape(message)}</text>
  </svg>
</figure>"""


# --- the page ---------------------------------------------------------------


def _tiles(stats: dict, has_live: bool) -> str:
    if not stats.get("trades"):
        return '<p class="note">No trades journalled yet.</p>'

    def tile(label: str, value: str, tone: str = "") -> str:
        return (
            f'<div class="tile"><div class="tile-label">{html.escape(label)}</div>'
            f'<div class="tile-value {tone}">{html.escape(value)}</div></div>'
        )

    pf = stats["profit_factor"]
    return (
        '<div class="tiles">'
        + tile("Trades", f"{stats['trades']:,}")
        + tile("Total R", f"{stats['total_r']:+.2f}",
               "pos" if stats["total_r"] >= 0 else "neg")
        + tile("Expectancy", f"{stats['expectancy_r']:+.3f}R",
               "pos" if stats["expectancy_r"] >= 0 else "neg")
        + tile("Win rate", _pct(stats["win_rate"]))
        + tile("Profit factor", "∞" if pf == float("inf") else f"{pf:.2f}")
        + tile("Max drawdown", _pct(stats["max_drawdown"]))
        + "</div>"
    )


def _gates(gates: list[Gate]) -> str:
    """The gates, each opening to show what would move it.

    A native <details> rather than a scripted toggle: it is keyboard reachable
    without any ARIA, it prints open, and it works with scripting off. The gate
    that is actually next is open on load, so "what do I do" needs no click.
    """
    icons = {"good": "✓", "critical": "✕", "warning": "…", "muted": "○"}
    rows = []
    for index, gate in enumerate(gates, start=1):
        icon = icons.get(gate.status, "○")
        head = (
            f'<summary class="gate-head">'
            f'<span class="gate-icon" aria-hidden="true">{icon}</span>'
            f'<span class="gate-name"><span class="gate-no">{index}</span>'
            f"{html.escape(gate.name)}</span>"
            f'<span class="gate-state">{html.escape(gate.state)}</span>'
            f'<span class="gate-detail">{html.escape(gate.detail)}</span>'
            "</summary>"
        )

        if not gate.has_body:
            rows.append(f'<div class="gate {gate.status} flat">{head}</div>')
            continue

        body = []
        if gate.what:
            body.append(f'<p class="what">{html.escape(gate.what)}</p>')
        if gate.steps:
            items = "".join(
                f"<li>{html.escape(text)}"
                + (f"<code>{html.escape(command)}</code>" if command else "")
                + "</li>"
                for text, command in gate.steps
            )
            body.append(f'<ol class="steps">{items}</ol>')
        if gate.done_when:
            body.append(
                f'<p class="donewhen"><strong>Done when</strong> '
                f"{html.escape(gate.done_when)}</p>"
            )

        rows.append(
            f'<details class="gate {gate.status}"'
            + (" open" if gate.next_up else "")
            + f'>{head}<div class="gate-body">{"".join(body)}</div></details>'
        )
    return f'<div class="gates">{"".join(rows)}</div>'


def _table(frame: pd.DataFrame, limit: int = 60) -> str:
    """The journal itself, which is also the table view the charts need."""
    if frame.empty:
        return ""
    shown = frame.sort_values("closed_at", ascending=False).head(limit)
    head = (
        "<tr><th>Closed</th><th>Model</th><th>Dir</th><th>Session</th>"
        "<th class=\"num\">R</th><th class=\"num\">Net</th>"
        "<th>Outcome</th><th>Source</th></tr>"
    )
    rows = []
    for row in shown.itertuples():
        tone = "pos" if row.r_multiple >= 0 else "neg"
        closed = pd.Timestamp(row.closed_at).tz_convert(MARKET_TZ)
        rows.append(
            "<tr>"
            f"<td>{closed:%d %b %Y %H:%M}</td>"
            f"<td>{html.escape(str(row.model))}</td>"
            f"<td>{html.escape(str(row.direction))}</td>"
            f"<td>{html.escape(str(row.session) if str(row.session) != 'nan' else '—')}</td>"
            f'<td class="num {tone}">{row.r_multiple:+.2f}</td>'
            f'<td class="num {tone}">{_money(row.net)}</td>'
            f"<td>{html.escape(str(row.outcome))}</td>"
            f"<td>{html.escape(str(row.source))}</td>"
            "</tr>"
        )
    more = (
        f'<p class="note">Showing the most recent {limit} of {len(frame):,} trades. '
        "The full record is the journal CSV.</p>"
        if len(frame) > limit
        else ""
    )
    return (
        '<div class="tablewrap"><table><thead>'
        + head
        + "</thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        + more
    )


def build_page(board: Dashboard) -> str:
    """Render the dashboard as one self contained HTML string."""
    stats = summarise(board.journal)
    sources = ", ".join(board.sources) if board.sources else "nothing yet"

    banner = ""
    if not stats.get("trades"):
        banner = (
            '<div class="banner"><strong>Nothing has been traded yet.</strong> '
            "This page is the plan, and the gates standing in front of it. The "
            "first gate needs a person rather than code: see "
            "<code>docs/labelling.md</code>.</div>"
        )
    elif not board.has_live:
        banner = (
            '<div class="banner"><strong>No live money in this record.</strong> '
            f"Every figure below comes from {html.escape(sources)}. "
            "Until the detectors pass the hand labelling gate, these numbers "
            "describe what the code did, not what the market does.</div>"
        )

    light = "".join(f"    --{k}: {v};\n" for k, v in PALETTE["light"].items())
    dark = "".join(f"      --{k}: {v};\n" for k, v in PALETTE["dark"].items())

    # Empty chart cards are worse than no cards: they take the space of a
    # result and deliver the absence of one.
    if stats.get("trades"):
        charts = equity_svg(board.journal) + daily_svg(board.journal)
        charts += breakdown_svg(board.journal, "model", "Total R by model")
        charts += breakdown_svg(board.journal, "session", "Total R by session")
    else:
        charts = ""

    return _TEMPLATE.format(
        title=html.escape(board.title),
        light=light,
        dark=dark,
        banner=banner,
        generated=board.generated_at.tz_convert(MARKET_TZ).strftime(
            "%d %B %Y, %H:%M New York"
        ),
        span=(
            f"{pd.Timestamp(stats['first']).tz_convert(MARKET_TZ):%d %b %Y} to "
            f"{pd.Timestamp(stats['last']).tz_convert(MARKET_TZ):%d %b %Y}"
            if stats.get("trades")
            else "no trades yet"
        ),
        tiles=_tiles(stats, board.has_live),
        gates=_gates(board.gates),
        charts=charts,
        table=_table(board.journal),
    )


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    color-scheme: light;
{light}  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      color-scheme: dark;
{dark}    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--surface); color: var(--ink);
    font: 15px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 920px; margin: 0 auto; padding: 32px 16px 72px; }}
  header {{ margin-bottom: 28px; }}
  h1 {{ font-size: clamp(22px, 4vw, 30px); margin: 0 0 6px; letter-spacing: -0.02em; }}
  .sub {{ color: var(--ink2); margin: 0; font-size: 14px; }}
  h2 {{
    font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 40px 0 14px; font-weight: 650;
  }}
  .banner {{
    background: var(--panel); border: 1px solid var(--axis);
    border-left: 3px solid var(--warning);
    border-radius: 10px; padding: 14px 16px; margin: 20px 0 0;
    font-size: 14px; color: var(--ink2);
  }}
  .banner strong {{ color: var(--ink); }}
  .tiles {{
    display: grid; gap: 10px; margin-top: 8px;
    grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  }}
  .tile {{
    background: var(--panel); border: 1px solid var(--axis);
    border-radius: 10px; padding: 12px 14px;
  }}
  .tile-label {{
    font-size: 12px; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .tile-value {{
    font-size: 23px; font-weight: 640; margin-top: 2px;
    font-variant-numeric: tabular-nums; letter-spacing: -0.01em;
    white-space: nowrap;
  }}
  .pos {{ color: var(--pos); }}
  .neg {{ color: var(--neg); }}
  .gates {{ margin: 0; padding: 0; }}
  .gate {{
    background: var(--panel); border: 1px solid var(--axis);
    border-radius: 10px; margin-bottom: 7px;
  }}
  .gate-head {{
    display: grid; align-items: baseline; gap: 4px 12px;
    grid-template-columns: 20px 1fr auto 14px;
    padding: 11px 14px; cursor: pointer; list-style: none;
    border-radius: 10px;
  }}
  .gate.flat .gate-head {{ cursor: default; }}
  .gate-head::-webkit-details-marker {{ display: none; }}
  .gate-head:hover {{ background: color-mix(in srgb, var(--ink) 4%, transparent); }}
  .gate-head:focus-visible {{
    outline: 2px solid var(--pos); outline-offset: -2px;
  }}
  .gate-head::after {{
    content: "+"; color: var(--muted); font-weight: 600;
    grid-column: 4; grid-row: 1; justify-self: end; align-self: center;
    font-size: 15px; line-height: 1;
  }}
  .gate[open] .gate-head::after {{ content: "−"; }}
  .gate.flat .gate-head::after {{ content: ""; }}
  .gate-icon {{ font-weight: 700; text-align: center; }}
  .gate-no {{
    display: inline-block; min-width: 18px; color: var(--muted);
    font-variant-numeric: tabular-nums;
  }}
  .gate.good .gate-icon {{ color: var(--good); }}
  .gate.critical .gate-icon {{ color: var(--critical); }}
  .gate.warning .gate-icon {{ color: var(--warning); }}
  .gate.muted .gate-icon {{ color: var(--muted); }}
  .gate-state {{
    font-size: 12px; color: var(--ink2); text-transform: uppercase;
    letter-spacing: 0.05em; white-space: nowrap;
  }}
  .gate-detail {{
    grid-column: 2 / -1; font-size: 13px; color: var(--muted);
  }}
  .gate-detail:empty {{ display: none; }}
  .gate-body {{
    padding: 2px 16px 16px 46px; border-top: 1px solid var(--axis);
    margin-top: 2px;
  }}
  .gate-body .what {{
    margin: 14px 0 12px; font-size: 14px; color: var(--ink2);
    max-width: 62ch;
  }}
  .steps {{ margin: 0; padding-left: 20px; font-size: 14px; }}
  .steps li {{ margin-bottom: 10px; color: var(--ink2); max-width: 62ch; }}
  .steps li::marker {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
  code {{
    padding: 1px 5px; background: var(--surface);
    border: 1px solid var(--axis); border-radius: 5px; color: var(--ink);
    font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  .steps code {{
    display: block; margin-top: 6px; padding: 8px 10px; border-radius: 6px;
    /* Wrapped rather than scrolled: a clipped command is one a reader
       retypes wrongly, and these are long by nature. */
    white-space: pre-wrap; overflow-wrap: anywhere; max-width: 100%;
  }}
  .donewhen {{
    margin: 14px 0 0; font-size: 14px; color: var(--ink2);
    padding-top: 12px; border-top: 1px solid var(--axis); max-width: 62ch;
  }}
  .donewhen strong {{ color: var(--ink); }}

  .chart {{
    margin: 0 0 26px; background: var(--panel);
    border: 1px solid var(--axis); border-radius: 12px; padding: 14px 16px 10px;
    position: relative; overflow: visible;
  }}
  figcaption {{ font-size: 13px; color: var(--ink2); margin-bottom: 8px; }}
  svg {{ width: 100%; height: auto; display: block; overflow: visible; }}
  .grid {{ stroke: var(--axis); stroke-width: 1; opacity: 0.45; }}
  .zero {{ stroke: var(--axis); stroke-width: 1.5; }}
  .crosshair {{ stroke: var(--muted); stroke-width: 1; stroke-dasharray: 3 3; }}
  .tick, .rowlabel, .value {{
    font-size: 11px; fill: var(--muted); font-variant-numeric: tabular-nums;
  }}
  .rowlabel {{ fill: var(--ink2); font-size: 12px; }}
  .value {{ fill: var(--ink2); font-size: 12px; font-weight: 600; }}
  .tip {{
    position: absolute; pointer-events: none; z-index: 3;
    background: var(--ink); color: var(--surface);
    padding: 6px 9px; border-radius: 7px; font-size: 12px;
    font-variant-numeric: tabular-nums; white-space: nowrap;
    transform: translate(-50%, -140%);
  }}
  .tablewrap {{
    overflow-x: auto; border: 1px solid var(--axis); border-radius: 12px;
    background: var(--panel);
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 9px 12px; text-align: left; white-space: nowrap; }}
  th {{
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--muted); border-bottom: 1px solid var(--axis); font-weight: 600;
  }}
  tbody tr + tr td {{ border-top: 1px solid var(--axis); }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .note {{ font-size: 13px; color: var(--muted); margin: 10px 2px 0; }}
  footer {{
    margin-top: 48px; padding-top: 18px; border-top: 1px solid var(--axis);
    font-size: 13px; color: var(--muted);
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{title}</h1>
    <p class="sub">Generated {generated} · {span}</p>
    {banner}
  </header>

  <h2>Validation gates</h2>
  {gates}

  <h2>Results</h2>
  {tiles}

  {charts}

  <h2>Journal</h2>
  {table}

  <footer>
    An engineering and research project, not financial advice. Leveraged
    trading carries a high risk of loss. The kill switch is
    <code>ict flatten</code> on the command line, not a button here: this page
    is meant to be shared, and a button that closes positions would need a
    live trading token inside a shared file.
  </footer>
</div>

<script>
// Crosshair and tooltip for the equity line. Bars carry a native <title>,
// which is enough for a single value and works without scripting.
for (const fig of document.querySelectorAll(".chart")) {{
  const svg = fig.querySelector("svg.equity");
  if (!svg) continue;
  const points = JSON.parse(svg.dataset.hover || "[]");
  if (!points.length) continue;
  const tip = fig.querySelector(".tip");
  const cursor = svg.querySelector(".cursor");
  const cross = svg.querySelector(".crosshair");
  const box = svg.viewBox.baseVal;

  function nearest(px) {{
    let best = points[0], gap = Infinity;
    for (const p of points) {{
      const d = Math.abs(p.x - px);
      if (d < gap) {{ gap = d; best = p; }}
    }}
    return best;
  }}

  svg.addEventListener("pointermove", (ev) => {{
    const rect = svg.getBoundingClientRect();
    const px = ((ev.clientX - rect.left) / rect.width) * box.width;
    const p = nearest(px);
    cursor.setAttribute("cx", p.x); cursor.setAttribute("cy", p.y);
    cursor.setAttribute("opacity", "1");
    cross.setAttribute("x1", p.x); cross.setAttribute("x2", p.x);
    cross.setAttribute("opacity", "1");
    tip.hidden = false;
    tip.textContent = p.r.toFixed(2) + "R · " + p.t;
    tip.style.left = ((p.x / box.width) * rect.width) + "px";
    tip.style.top = ((p.y / box.height) * rect.height) + "px";
  }});
  svg.addEventListener("pointerleave", () => {{
    cursor.setAttribute("opacity", "0");
    cross.setAttribute("opacity", "0");
    tip.hidden = true;
  }});
}}
</script>
</body>
</html>
"""


def build(
    journal_path: str | Path | None = None,
    title: str = "ICT trading system",
    gates: list[Gate] | None = None,
) -> Dashboard:
    """Assemble a dashboard from a journal file."""
    frame = pd.DataFrame()
    if journal_path and Path(journal_path).exists():
        frame = read_journal(journal_path)

    sources = (
        sorted({str(s) for s in frame["source"].dropna()})
        if not frame.empty and "source" in frame.columns
        else []
    )
    return Dashboard(
        title=title,
        journal=frame,
        gates=gates or default_gates(frame),
        sources=sources,
    )


def default_gates(frame: pd.DataFrame) -> list[Gate]:
    """The six gates, filled in from what is actually on disk.

    Everything defaults to not started. A gate is only marked passed by
    evidence, never by the absence of a failure.

    Each carries the commands that would move it, so the page answers "what do
    I do next" rather than only "where am I". The first gate that is not
    finished is marked ``next_up`` and opens on load.
    """
    live = not frame.empty and "live" in set(frame.get("source", []))
    paper = not frame.empty and "paper" in set(frame.get("source", []))
    paper_trades = (
        int((frame["source"] == "paper").sum()) if not frame.empty else 0
    )

    gates = [
        Gate(
            GATES[0][0],
            "not started",
            f"Needs 100 hand marked charts per concept at {PASS_THRESHOLD:.0%} "
            "agreement.",
            what=(
                "The detectors must agree with a person. Until they do, a "
                "'sweep' the code found might not be one, and every result "
                "below it describes the code rather than the market. This is "
                "the only gate that cannot be automated, and it is the one "
                "most likely to end the project."
            ),
            steps=(
                ("Get real data first, from gate 2. Marking a random walk "
                 "means marking patterns that are not there.", ""),
                ("Build the labelling page, a hundred charts at a time.",
                 "ict label data/processed/eurusd_m1.parquet --count 100 "
                 "--timeframe 15m --out labelling.html"),
                ("Open it and click the candles. q a w s e d pick the "
                 "concept; 0 records a chart with nothing on it.", ""),
                ("Press Download labels, then score your marks against the "
                 "detectors.",
                 "ict verify data/processed/eurusd_m1.parquet "
                 "--labels labels.csv --reviewed reviewed.csv"),
                ("Tune against the agreement numbers, never against backtest "
                 "results. Start with mss_prominence_lookback in config.py.", ""),
            ),
            done_when=(
                "ict verify exits zero, meaning every concept is at or above "
                "90% agreement over 100 charts. Expect several rounds."
            ),
        ),
        Gate(
            GATES[1][0],
            "not started",
            "Needs real data.",
            what=(
                "Three years of 1 minute EUR/USD with spread, commission and "
                "slippage modelled. A free OANDA practice account supplies "
                "both the history and, later, the execution."
            ),
            steps=(
                ("Open a practice account at oanda.com and generate a token "
                 "under Manage API Access. It needs no deposit.", ""),
                ("Put the credentials in the environment. Never in the "
                 "repository.",
                 "export OANDA_API_TOKEN=... OANDA_ACCOUNT_ID=... "
                 "OANDA_ENVIRONMENT=practice"),
                ("Download the history. It resumes if interrupted.",
                 "ict fetch --start 2021-01-01 "
                 "--out data/processed/eurusd_m1.parquet"),
                ("Check for holes. Weekend closes are expected; anything else "
                 "is a data problem.",
                 "ict gaps data/processed/eurusd_m1.parquet"),
                ("Run the backtest once gate 1 has passed.",
                 "ict backtest data/processed/eurusd_m1.parquet --verified"),
            ),
            done_when=(
                "profit factor above 1.3, expectancy above 0.2R, maximum "
                "drawdown below 15%, and at least 200 trades."
            ),
        ),
        Gate(
            GATES[2][0],
            "not started",
            "Blocked on the gate above.",
            what=(
                "Tuning and reporting on the same data measures how well the "
                "search fitted that data. This tunes on a rolling window and "
                "reports only the window after it."
            ),
            steps=(
                ("Roll a year of tuning against the quarter that follows it.",
                 "ict rank data/processed/eurusd_m1.parquet "
                 "--train-days 365 --test-days 90"),
                ("Read the drift column before the expectancy column. Large "
                 "positive drift means the tuning fitted noise.", ""),
                ("Ignore any model with fewer than about thirty trades, "
                 "whatever it scored.", ""),
            ),
            done_when=(
                "a model clears the pass criteria out of sample, on enough "
                "trades to mean something, with drift near zero."
            ),
        ),
        Gate(
            GATES[3][0],
            "not started",
            "Blocked on the gate above.",
            what=(
                "A real edge degrades gently when a parameter moves, and "
                "survives its trades arriving in a different order. This "
                "checks both."
            ),
            steps=(
                ("Run the sensitivity sweep and the Monte Carlo together. It "
                 "exits non-zero unless both halves pass.",
                 "ict robustness data/processed/eurusd_m1.parquet "
                 "--model silver_bullet"),
                ("Size positions off the 95th percentile drawdown, not the "
                 "one that happened to occur.", ""),
            ),
            done_when=(
                "most neighbouring settings stay profitable and the expectancy "
                "interval clears zero. An interval spanning zero means the "
                "edge is not established, whatever the total says."
            ),
        ),
        Gate(
            GATES[4][0],
            "running" if paper else "not started",
            f"{paper_trades} paper trades journalled; needs 100 or three months."
            if paper
            else "Blocked on the gates above.",
            what=(
                "The same code that was backtested, trading a practice "
                "account with real fills, real spread and real latency. No "
                "money at risk: practice and live differ only by hostname."
            ),
            steps=(
                ("Watch it decide without sending anything first.",
                 "ict live data/processed/eurusd_m1.parquet "
                 "--calendar week.csv"),
                ("When the log looks right, let it trade the practice "
                 "account.",
                 "ict live data/processed/eurusd_m1.parquet --calendar "
                 "week.csv --execute --trade-journal journal.csv"),
                ("Set the halt from the worst drawdown the backtest saw, not "
                 "from what feels tolerable.", ""),
                ("Review the record after each session.",
                 "ict journal journal.csv --daily"),
            ),
            done_when=(
                "three months or 100 trades, with results inside the range the "
                "backtest predicted. Outside it means the backtest was wrong, "
                "and a practice account is the cheapest place to find out."
            ),
        ),
        Gate(
            GATES[5][0],
            "running" if live else "not started",
            "" if live else "Blocked on the gates above.",
            what=(
                "Minimum position size for three months. The question here is "
                "whether the system behaves with real fills and real spread "
                "widening, and that is answered just as well with tiny size."
            ),
            steps=(
                ("Change one environment variable.",
                 "export OANDA_ENVIRONMENT=live"),
                ("The extra flag is required against the live host, so this is "
                 "a decision rather than a typo.",
                 "ict live ... --execute --i-understand"),
                ("Keep the kill switch to hand.", "ict flatten"),
            ),
            done_when=(
                "three months at minimum size with no surprises. Only then is "
                "scaling a question worth asking."
            ),
        ),
    ]

    # Mark the first unfinished gate, so the page opens on the work that is
    # actually next rather than on the first row.
    for gate in gates:
        if gate.state != "passed":
            gate.next_up = True
            break
    return gates
