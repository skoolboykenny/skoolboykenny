"""A click to mark labelling app, because the CSV workflow will not get finished.

Gate 1 is the only thing blocking this project, and it is blocked on a person
spending hours marking charts. The original workflow asked that person to open
a chart, read a timestamp off it by eye, and type a row into a CSV, six
hundred times. That is not a fifteen hour job, it is an unbounded one, and the
timestamps read by eye are why the scorer needs a two candle tolerance in the
first place.

This module builds one self contained page holding every sampled chart. A
click places a mark on the exact candle under the cursor, a key chooses the
concept, and the page keeps a running count. Work is saved to the browser as
it goes, so closing the tab does not lose an evening.

**It still shows no detector output.** That constraint is the whole point of
the gate: someone who can see what the code thinks will agree with it, and a
detector that is systematically wrong would sail through. Only the furniture
read off the clock is drawn, the kill zone shading and the session levels.

The page writes the same ``labels.csv`` the scorer already reads, plus a
``reviewed.csv`` naming every chart that was finished. The second file matters
more than it looks: without it, a chart where someone correctly saw nothing
contributes no rows, so the detector's false positives on that chart are never
counted, and a detector that over-fires on quiet days passes the gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import MARKET_TZ
from .detectors.levels import session_levels
from .timeframes.sessions import KILL_ZONES

#: Concept, the key that marks it, and how it is drawn. Keys are chosen so a
#: right handed person can reach all six without moving off the home row.
MARKERS: tuple[tuple[str, str, str, str], ...] = (
    ("swing_high", "q", "#e06c75", "triangle-down"),
    ("swing_low", "a", "#61afef", "triangle-up"),
    ("sweep", "w", "#e5c07b", "x"),
    ("mss", "s", "#c678dd", "diamond"),
    ("fvg", "e", "#98c379", "square"),
    ("order_block", "d", "#56b6c2", "circle"),
)


@dataclass
class Chart:
    """One day of candles, ready to be embedded in the page."""

    date: str
    timeframe: str
    times: list[int] = field(default_factory=list)
    opens: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)
    levels: list[dict] = field(default_factory=list)
    zones: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "date": self.date,
            "timeframe": self.timeframe,
            "t": self.times,
            "o": self.opens,
            "h": self.highs,
            "l": self.lows,
            "c": self.closes,
            "levels": self.levels,
            "zones": self.zones,
        }


def build_chart(frame: pd.DataFrame, date: str, timeframe: str) -> Chart:
    """Turn one day's candles into the arrays the page draws.

    Times are milliseconds since the epoch in **New York wall clock**, because
    that is what the chart is read in and what the labels file stores. The
    page never converts a timezone, so it cannot get one wrong.
    """
    local = frame.tz_convert(MARKET_TZ)
    stamps = local.index
    times = (
        stamps.tz_localize(None).astype("datetime64[ms]").astype("int64").tolist()
    )

    chart = Chart(
        date=date,
        timeframe=timeframe,
        times=times,
        opens=[float(v) for v in frame["open"]],
        highs=[float(v) for v in frame["high"]],
        lows=[float(v) for v in frame["low"]],
        closes=[float(v) for v in frame["close"]],
    )

    if timeframe == "1m":
        chart.levels = _levels(frame)
    chart.zones = _kill_zones(local)
    return chart


def _levels(frame: pd.DataFrame) -> list[dict]:
    """Session levels, which are read off the clock rather than inferred.

    Safe to draw: they are not a detector's opinion about structure, they are
    where yesterday closed. Leaving them off would make the charts harder to
    read without making the test any fairer.
    """
    try:
        levels = session_levels(frame)
    except Exception:
        return []
    if levels.empty:
        return []
    return [
        {"name": str(row.name_), "price": float(row.price)}
        for row in levels.rename(columns={"name": "name_"}).itertuples()
        if pd.notna(row.price)
    ]


def _kill_zones(local: pd.DatetimeIndex | pd.DataFrame) -> list[dict]:
    """Kill zone bands as wall clock minute offsets into the day."""
    zones = []
    for window in KILL_ZONES:
        start = window.start.hour * 60 + window.start.minute
        end = window.end.hour * 60 + window.end.minute
        zones.append(
            {
                "name": window.name,
                "start": start,
                "end": end,
                "crosses": bool(window.crosses_midnight),
            }
        )
    return zones


def plotly_script() -> str:
    """The Plotly bundle, inlined rather than fetched from a CDN.

    Labelling is a long offline job: hours on a laptop, possibly on a train,
    and a page that needs the network to draw its first chart is a page that
    fails at the worst moment. The bundle ships with the plotly package
    already, so inlining costs nothing but file size, and a self contained
    file can also be copied to another machine and still work.
    """
    import plotly

    bundle = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    if bundle.exists():
        return f"<script>{bundle.read_text(encoding='utf-8')}</script>"
    # Fall back to the CDN if the package layout ever changes, and say so.
    return (
        '__PLOTLY__'
        "<!-- inlined bundle not found; this page now needs the network -->"
    )


def build_page(charts: list[Chart], title: str = "ICT labelling") -> str:
    """Render the whole labelling app as one HTML string."""
    payload = json.dumps([c.as_dict() for c in charts], separators=(",", ":"))
    markers = json.dumps(
        [
            {"concept": c, "key": k, "colour": col, "symbol": sym}
            for c, k, col, sym in MARKERS
        ]
    )
    return (
        _TEMPLATE.replace("__PLOTLY__", plotly_script())
        .replace("__CHARTS__", payload)
        .replace("__MARKERS__", markers)
        .replace("__TITLE__", title)
    )


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
__PLOTLY__
<style>
  :root {
    --bg: #ffffff; --panel: #f4f5f7; --ink: #1b1d21; --muted: #5c6370;
    --line: #d8dade; --accent: #2f6feb;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #16181d; --panel: #1f2229; --ink: #e6e8ec; --muted: #9aa0ab;
      --line: #2e323b; --accent: #4f8cff;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
  }
  header {
    display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
    padding: 10px 16px; background: var(--panel);
    border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 5;
  }
  h1 { font-size: 15px; margin: 0 12px 0 0; font-weight: 650; }
  .grow { flex: 1; }
  button {
    font: inherit; padding: 6px 12px; border-radius: 7px;
    border: 1px solid var(--line); background: var(--bg); color: var(--ink);
    cursor: pointer;
  }
  button:hover { border-color: var(--accent); }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .keys { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 16px;
          border-bottom: 1px solid var(--line); }
  .key {
    display: flex; align-items: center; gap: 7px; padding: 5px 11px;
    border-radius: 999px; border: 1px solid var(--line); cursor: pointer;
    background: var(--bg); user-select: none;
  }
  .key[aria-pressed="true"] { border-color: var(--accent); border-width: 2px; padding: 4px 10px; }
  .swatch { width: 11px; height: 11px; border-radius: 3px; }
  kbd {
    font: 600 11px ui-monospace, SFMono-Regular, Menlo, monospace;
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 4px; padding: 1px 5px;
  }
  .count { color: var(--muted); font-variant-numeric: tabular-nums; }
  #chart { width: 100%; height: calc(100vh - 190px); min-height: 380px; }
  footer {
    padding: 8px 16px; color: var(--muted); font-size: 12px;
    border-top: 1px solid var(--line); background: var(--panel);
  }
  .pill { padding: 2px 8px; border-radius: 999px; background: var(--bg);
          border: 1px solid var(--line); font-variant-numeric: tabular-nums; }
  @media (max-width: 720px) {
    header { gap: 8px; } h1 { width: 100%; }
    #chart { height: 60vh; }
  }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <button id="prev">&larr; Prev</button>
  <span class="pill" id="position">1 / 1</span>
  <button id="next">Next &rarr;</button>
  <span class="pill" id="day">-</span>
  <span class="count" id="marks">0 marks</span>
  <span class="grow"></span>
  <button id="none">Nothing here <kbd>0</kbd></button>
  <button id="undo">Undo <kbd>u</kbd></button>
  <button id="save" class="primary">Download labels</button>
</header>

<div class="keys" id="keys"></div>
<div id="chart"></div>

<footer>
  Click a candle to mark it with the selected concept. The detectors' own
  output is deliberately not shown: seeing it first would make you agree with
  it. Work is saved in this browser as you go.
  <span id="progress"></span>
</footer>

<script>
const CHARTS = __CHARTS__;
const MARKERS = __MARKERS__;
const STORE = "ict-labels-v1";

let index = 0;
let concept = MARKERS[0].concept;
// marks[chartKey] = [{t, concept}]; reviewed is a set of chart keys.
let state = { marks: {}, reviewed: [] };

const keyOf = (c) => c.date + "|" + c.timeframe;

function load() {
  try {
    const raw = localStorage.getItem(STORE);
    if (raw) state = Object.assign(state, JSON.parse(raw));
  } catch (e) { /* private window, or storage off: carry on unsaved */ }
}
function save() {
  try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) {}
}

function marksFor(chart) {
  const k = keyOf(chart);
  if (!state.marks[k]) state.marks[k] = [];
  return state.marks[k];
}

function drawKeys() {
  const host = document.getElementById("keys");
  host.innerHTML = "";
  for (const m of MARKERS) {
    const el = document.createElement("div");
    el.className = "key";
    el.setAttribute("role", "button");
    el.setAttribute("aria-pressed", String(m.concept === concept));
    el.dataset.concept = m.concept;
    el.innerHTML =
      '<span class="swatch" style="background:' + m.colour + '"></span>' +
      '<span>' + m.concept.replace(/_/g, " ") + '</span>' +
      '<kbd>' + m.key + '</kbd>' +
      '<span class="count" data-count="' + m.concept + '"></span>';
    el.onclick = () => { concept = m.concept; drawKeys(); };
    host.appendChild(el);
  }
  updateCounts();
}

function updateCounts() {
  const chart = CHARTS[index];
  const marks = marksFor(chart);
  for (const m of MARKERS) {
    const n = marks.filter((x) => x.concept === m.concept).length;
    const el = document.querySelector('[data-count="' + m.concept + '"]');
    if (el) el.textContent = n ? String(n) : "";
  }
  document.getElementById("marks").textContent =
    marks.length + (marks.length === 1 ? " mark" : " marks");

  const done = state.reviewed.length;
  document.getElementById("progress").textContent =
    " · " + done + " of " + CHARTS.length + " charts finished";
}

function shapes(chart) {
  // Kill zone bands, drawn from the clock rather than from any detector.
  const out = [];
  if (!chart.t.length) return out;
  const dayStart = new Date(chart.t[0]);
  dayStart.setHours(0, 0, 0, 0);
  const base = dayStart.getTime();
  for (const z of chart.zones) {
    const from = base + z.start * 60000;
    const to = base + (z.crosses ? z.end + 1440 : z.end) * 60000;
    out.push({
      type: "rect", xref: "x", yref: "paper", x0: from, x1: to, y0: 0, y1: 1,
      fillcolor: "rgba(120,140,190,0.09)", line: { width: 0 }, layer: "below",
    });
  }
  for (const lv of chart.levels) {
    out.push({
      type: "line", xref: "paper", yref: "y", x0: 0, x1: 1,
      y0: lv.price, y1: lv.price, layer: "below",
      line: { width: 1, dash: "dot", color: "rgba(140,150,170,0.75)" },
    });
  }
  return out;
}

function render() {
  const chart = CHARTS[index];
  const marks = marksFor(chart);

  const candles = {
    type: "candlestick", x: chart.t.map((v) => new Date(v)),
    open: chart.o, high: chart.h, low: chart.l, close: chart.c,
    increasing: { line: { color: "#3fa96a" } },
    decreasing: { line: { color: "#d05a5a" } },
    hoverinfo: "x+y", name: "",
  };

  const traces = [candles];
  for (const m of MARKERS) {
    const mine = marks.filter((x) => x.concept === m.concept);
    if (!mine.length) continue;
    traces.push({
      type: "scatter", mode: "markers",
      x: mine.map((x) => new Date(x.t)),
      y: mine.map((x) => priceAt(chart, x.t, m.concept)),
      marker: { symbol: m.symbol, size: 13, color: m.colour,
                line: { width: 1, color: "rgba(0,0,0,0.35)" } },
      name: m.concept, hoverinfo: "name+x",
    });
  }

  Plotly.react("chart", traces, {
    // Right margin fits a five decimal forex price; 14px clipped them.
    margin: { l: 14, r: 76, t: 8, b: 40 },
    dragmode: "pan",
    xaxis: { rangeslider: { visible: false }, gridcolor: "rgba(130,140,160,0.18)" },
    yaxis: { side: "right", gridcolor: "rgba(130,140,160,0.18)",
             tickformat: ".5f", automargin: true },
    shapes: shapes(chart),
    showlegend: false,
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: getComputedStyle(document.body).color },
  }, { displayModeBar: true, responsive: true, scrollZoom: true });

  document.getElementById("position").textContent =
    (index + 1) + " / " + CHARTS.length;
  document.getElementById("day").textContent =
    chart.date + " · " + chart.timeframe +
    (state.reviewed.includes(keyOf(chart)) ? " · done" : "");
  updateCounts();
  bindClicks();
}

function priceAt(chart, t, concept) {
  // Put the mark where the eye expects it: highs above, lows below, the rest
  // on the close.
  let best = 0, gap = Infinity;
  for (let i = 0; i < chart.t.length; i++) {
    const d = Math.abs(chart.t[i] - t);
    if (d < gap) { gap = d; best = i; }
  }
  const span = (chart.h[best] - chart.l[best]) || 0.0002;
  if (concept === "swing_high") return chart.h[best] + span * 0.6;
  if (concept === "swing_low") return chart.l[best] - span * 0.6;
  return chart.c[best];
}

function snap(chart, ms) {
  let best = chart.t[0], gap = Infinity;
  for (const t of chart.t) {
    const d = Math.abs(t - ms);
    if (d < gap) { gap = d; best = t; }
  }
  return best;
}

function bindClicks() {
  // Not plotly_click: that only fires when the cursor is over a candle body,
  // so half the clicks in a session land on empty space and do nothing, which
  // feels broken and costs far more time than it sounds. Instead the drag
  // layer takes the click and the x pixel is converted to a time, then
  // snapped to the nearest candle. Anywhere in the column works.
  const gd = document.getElementById("chart");
  const drag = gd.querySelector(".nsewdrag");
  if (!drag || drag.dataset.bound === "1") return;
  drag.dataset.bound = "1";

  // Plotly's pan handler consumes mouseup on this element, so only mousedown
  // and click actually arrive. mousedown records where the press started and
  // click does the work, which also means a pan never leaves a stray mark
  // because the browser suppresses click after a drag.
  let downAt = null;
  drag.addEventListener("mousedown", (ev) => { downAt = [ev.clientX, ev.clientY]; });
  drag.addEventListener("click", (ev) => {
    const moved = downAt
      ? Math.abs(ev.clientX - downAt[0]) + Math.abs(ev.clientY - downAt[1])
      : 0;
    downAt = null;
    if (moved > 4) return;
    placeMark(ev.clientX);
  });
}

function placeMark(clientX) {
  const gd = document.getElementById("chart");
  const drag = gd.querySelector(".nsewdrag");
  const xa = gd._fullLayout && gd._fullLayout.xaxis;
  if (!drag || !xa || !xa.p2d) return;

  const bb = drag.getBoundingClientRect();
  const raw = xa.p2d(clientX - bb.left);
  const ms = typeof raw === "number" ? raw : new Date(raw).getTime();
  if (!isFinite(ms)) return;

  const chart = CHARTS[index];
  const t = snap(chart, ms);
  const marks = marksFor(chart);
  // A second click on the same candle with the same concept removes it, which
  // is the fastest way to fix a misclick.
  const at = marks.findIndex((m) => m.t === t && m.concept === concept);
  if (at >= 0) marks.splice(at, 1);
  else marks.push({ t: t, concept: concept });
  markReviewed(chart);
  save(); render();
}

function markReviewed(chart) {
  const k = keyOf(chart);
  if (!state.reviewed.includes(k)) state.reviewed.push(k);
}

function go(step) {
  index = (index + step + CHARTS.length) % CHARTS.length;
  render();
}

function csv(rows) {
  return rows.map((r) => r.map((v) => {
    const s = String(v ?? "");
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }).join(",")).join("\n") + "\n";
}

function stamp(ms) {
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
         " " + p(d.getHours()) + ":" + p(d.getMinutes());
}

function download(name, text) {
  const blob = new Blob([text], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function saveFiles() {
  const labels = [["date", "timeframe", "concept", "time", "note"]];
  for (const chart of CHARTS) {
    for (const m of (state.marks[keyOf(chart)] || [])) {
      labels.push([chart.date, chart.timeframe, m.concept, stamp(m.t), ""]);
    }
  }
  const reviewed = [["date", "timeframe"]];
  for (const k of state.reviewed) {
    const [date, timeframe] = k.split("|");
    reviewed.push([date, timeframe]);
  }
  download("labels.csv", csv(labels));
  // Charts looked at but not marked are the ones that catch a detector which
  // over-fires on quiet days, so they are recorded separately.
  setTimeout(() => download("reviewed.csv", csv(reviewed)), 350);
}

document.addEventListener("keydown", (ev) => {
  if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
  const k = ev.key.toLowerCase();
  const found = MARKERS.find((m) => m.key === k);
  if (found) { concept = found.concept; drawKeys(); return; }
  const chart = CHARTS[index];
  if (k === "arrowright" || k === "n") { go(1); ev.preventDefault(); }
  else if (k === "arrowleft" || k === "p") { go(-1); ev.preventDefault(); }
  else if (k === "u") {
    const marks = marksFor(chart);
    marks.pop(); save(); render();
  } else if (k === "0") {
    // "Nothing here" is a real answer and the gate needs it recorded.
    markReviewed(chart); save(); render(); go(1);
  }
});

document.getElementById("next").onclick = () => go(1);
document.getElementById("prev").onclick = () => go(-1);
document.getElementById("undo").onclick = () => {
  marksFor(CHARTS[index]).pop(); save(); render();
};
document.getElementById("none").onclick = () => {
  markReviewed(CHARTS[index]); save(); render(); go(1);
};
document.getElementById("save").onclick = saveFiles;

load();
drawKeys();
render();
</script>
</body>
</html>
"""
