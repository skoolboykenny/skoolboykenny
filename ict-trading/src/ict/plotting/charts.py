"""Annotated candlestick charts.

Everything is drawn on a New York time axis, because that is the clock the
concepts are defined on and reading a chart against any other one makes the
kill zones look wrong.

Verification is the real job here. A detector is trusted only once its output
has been compared against a hand-marked chart, so these plots exist to be
argued with, not admired: every zone carries the numbers behind it in its hover
text.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ..analysis import Analysis
from ..config import MARKET_TZ
from ..timeframes.sessions import KILL_ZONES, in_window

COLOURS = {
    "up": "#26A69A",
    "down": "#EF5350",
    "swing_high": "#EF5350",
    "swing_low": "#26A69A",
    "pool": "#F5C518",
    "sweep": "#AB47BC",
    "mss": "#1A6BFF",
    "bullish_fvg": "rgba(38,166,154,0.18)",
    "bearish_fvg": "rgba(239,83,80,0.18)",
    "order_block": "rgba(120,120,120,0.28)",
    "kill_zone": "rgba(245,197,24,0.07)",
    "level": "#8F8B7C",
}


def _ny(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index.tz_convert(MARKET_TZ)


def plot_analysis(
    analysis: Analysis,
    title: str | None = None,
    show_kill_zones: bool = True,
    show: tuple[str, ...] = (
        "swings",
        "pools",
        "sweeps",
        "mss",
        "fvgs",
        "order_blocks",
        "levels",
    ),
) -> go.Figure:
    """Draw candles with every detected concept annotated on top."""
    candles = analysis.candles
    if candles.empty:
        raise ValueError("nothing to plot: no candles in range")

    times = _ny(candles.index)
    figure = go.Figure()

    figure.add_trace(
        go.Candlestick(
            x=times,
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name=analysis.timeframe,
            increasing_line_color=COLOURS["up"],
            decreasing_line_color=COLOURS["down"],
        )
    )

    # Shapes are accumulated and assigned once. Calling add_shape in a loop
    # re-copies the whole layout each time, which turns a busy chart into a
    # quadratic wait.
    shapes: list[dict] = []
    notes: list[dict] = []

    if show_kill_zones:
        _draw_kill_zones(shapes, notes, candles)
    if "fvgs" in show:
        _draw_fvgs(shapes, analysis)
    if "order_blocks" in show:
        _draw_order_blocks(shapes, analysis)
    if "pools" in show:
        _draw_pools(figure, shapes, analysis)
    if "levels" in show:
        _draw_levels(shapes, notes, analysis)
    if "swings" in show:
        _draw_swings(figure, analysis)
    if "sweeps" in show:
        _draw_sweeps(figure, analysis)
    if "mss" in show:
        _draw_shifts(figure, shapes, analysis)

    figure.update_layout(shapes=shapes, annotations=notes)

    start, end = times[0], times[-1]
    figure.update_layout(
        title=title or f"{analysis.timeframe} · {start:%Y-%m-%d} New York time",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        height=760,
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom"},
        margin={"l": 60, "r": 30, "t": 70, "b": 40},
    )
    figure.update_xaxes(title="New York time", range=[start, end])
    figure.update_yaxes(title="price")
    return figure


def _draw_kill_zones(
    shapes: list[dict], notes: list[dict], candles: pd.DataFrame
) -> None:
    """Shade the kill zones as background bands."""
    for window in KILL_ZONES:
        if window.name.endswith("silver_bullet"):
            continue
        mask = in_window(candles.index, window)
        if not mask.any():
            continue
        for start, end in _contiguous_spans(candles.index[mask.to_numpy()]):
            x0 = _ny(pd.DatetimeIndex([start]))[0]
            x1 = _ny(pd.DatetimeIndex([end]))[0]
            shapes.append(
                {
                    "type": "rect",
                    "xref": "x",
                    "yref": "paper",
                    "x0": x0,
                    "x1": x1,
                    "y0": 0,
                    "y1": 1,
                    "fillcolor": COLOURS["kill_zone"],
                    "line": {"width": 0},
                    "layer": "below",
                }
            )
            notes.append(
                {
                    "x": x0,
                    "y": 1,
                    "xref": "x",
                    "yref": "paper",
                    "text": window.name.replace("_", " "),
                    "showarrow": False,
                    "xanchor": "left",
                    "yanchor": "bottom",
                    "font": {"size": 10, "color": COLOURS["level"]},
                }
            )


def _contiguous_spans(
    index: pd.DatetimeIndex, tolerance: str = "5min"
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Collapse a sparse index into the continuous runs it contains."""
    if not len(index):
        return []
    limit = pd.Timedelta(tolerance)
    spans = []
    start = previous = index[0]
    for stamp in index[1:]:
        if stamp - previous > limit:
            spans.append((start, previous))
            start = stamp
        previous = stamp
    spans.append((start, previous))
    return spans


def _draw_swings(figure: go.Figure, analysis: Analysis) -> None:
    for kind, symbol, colour in (
        ("high", "triangle-down", COLOURS["swing_high"]),
        ("low", "triangle-up", COLOURS["swing_low"]),
    ):
        points = analysis.swings.loc[analysis.swings["kind"] == kind]
        if points.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=_ny(pd.DatetimeIndex(points["time"])),
                y=points["price"],
                mode="markers",
                name=f"swing {kind}",
                marker={"symbol": symbol, "size": 9, "color": colour},
                customdata=points["confirmed_at"].astype(str),
                hovertemplate="swing %s %%{y}<br>confirmed %%{customdata}<extra></extra>"
                % kind,
            )
        )


def _draw_pools(figure: go.Figure, shapes: list[dict], analysis: Analysis) -> None:
    pools = analysis.pools
    if pools.empty:
        return
    times = _ny(analysis.candles.index)
    for _, pool in pools.iterrows():
        shapes.append(
            {
                "type": "line",
                "x0": _ny(pd.DatetimeIndex([pool["created_at"]]))[0],
                "x1": times[-1]
                if pd.isna(pool["swept_at"])
                else _ny(pd.DatetimeIndex([pool["swept_at"]]))[0],
                "y0": pool["price"],
                "y1": pool["price"],
                "line": {
                    "color": COLOURS["pool"],
                    "width": 2 if pool["is_equal_highs"] else 1,
                    "dash": "solid" if pool["is_equal_highs"] else "dot",
                },
                "layer": "below",
            }
        )
    figure.add_trace(
        go.Scatter(
            x=_ny(pd.DatetimeIndex(pools["created_at"])),
            y=pools["price"],
            mode="markers",
            name="liquidity pool",
            marker={"symbol": "line-ew", "size": 1, "color": COLOURS["pool"]},
            customdata=pools[["side", "touches"]],
            hovertemplate=(
                "pool %{y}<br>side %{customdata[0]}"
                "<br>touches %{customdata[1]}<extra></extra>"
            ),
        )
    )


def _draw_sweeps(figure: go.Figure, analysis: Analysis) -> None:
    sweeps = analysis.sweeps
    if sweeps.empty:
        return
    figure.add_trace(
        go.Scatter(
            x=_ny(pd.DatetimeIndex(sweeps["time"])),
            y=sweeps["extreme"],
            mode="markers",
            name="sweep",
            marker={
                "symbol": "x",
                "size": 11,
                "color": COLOURS["sweep"],
                "line": {"width": 1, "color": "white"},
            },
            customdata=sweeps[["side", "pool_price", "closed_back_at"]].astype(str),
            hovertemplate=(
                "sweep %{customdata[0]} side<br>pool %{customdata[1]}"
                "<br>closed back %{customdata[2]}<extra></extra>"
            ),
        )
    )


def _draw_shifts(figure: go.Figure, shapes: list[dict], analysis: Analysis) -> None:
    shifts = analysis.shifts
    if shifts.empty:
        return
    for _, shift in shifts.iterrows():
        shapes.append(
            {
                "type": "line",
                "x0": _ny(pd.DatetimeIndex([shift["sweep_time"]]))[0],
                "x1": _ny(pd.DatetimeIndex([shift["time"]]))[0],
                "y0": shift["level"],
                "y1": shift["level"],
                "line": {"color": COLOURS["mss"], "width": 2, "dash": "dash"},
            }
        )
    figure.add_trace(
        go.Scatter(
            x=_ny(pd.DatetimeIndex(shifts["time"])),
            y=shifts["level"],
            mode="markers+text",
            name="MSS",
            text=shifts["direction"].map({"up": "MSS ↑", "down": "MSS ↓"}),
            textposition="top center",
            textfont={"size": 10, "color": COLOURS["mss"]},
            marker={"symbol": "diamond", "size": 10, "color": COLOURS["mss"]},
            customdata=shifts[["sweep_time", "sweep_side"]].astype(str),
            hovertemplate=(
                "MSS at %{y}<br>after sweep %{customdata[1]} "
                "at %{customdata[0]}<extra></extra>"
            ),
        )
    )


def _draw_fvgs(shapes: list[dict], analysis: Analysis) -> None:
    gaps = analysis.fvgs
    if gaps.empty:
        return
    last = _ny(analysis.candles.index)[-1]
    for _, gap in gaps.iterrows():
        end = (
            last
            if pd.isna(gap["mitigated_at"])
            else _ny(pd.DatetimeIndex([gap["mitigated_at"]]))[0]
        )
        shapes.append(
            {
                "type": "rect",
                "x0": _ny(pd.DatetimeIndex([gap["time"]]))[0],
                "x1": end,
                "y0": gap["bottom"],
                "y1": gap["top"],
                "fillcolor": COLOURS[f"{gap['direction']}_fvg"],
                "line": {"width": 0},
                "layer": "below",
            }
        )


def _draw_order_blocks(shapes: list[dict], analysis: Analysis) -> None:
    blocks = analysis.order_blocks
    if blocks.empty:
        return
    last = _ny(analysis.candles.index)[-1]
    for _, block in blocks.iterrows():
        end = (
            last
            if pd.isna(block["mitigated_at"])
            else _ny(pd.DatetimeIndex([block["mitigated_at"]]))[0]
        )
        start = _ny(pd.DatetimeIndex([block["time"]]))[0]
        shapes.append(
            {
                "type": "rect",
                "x0": start,
                "x1": end,
                "y0": block["bottom"],
                "y1": block["top"],
                "fillcolor": COLOURS["order_block"],
                "line": {"width": 1, "color": COLOURS["level"]},
                "layer": "below",
            }
        )
        shapes.append(
            {
                "type": "line",
                "x0": start,
                "x1": end,
                "y0": block["mean_threshold"],
                "y1": block["mean_threshold"],
                "line": {"width": 1, "color": COLOURS["level"], "dash": "dot"},
                "layer": "below",
            }
        )


def _draw_levels(shapes: list[dict], notes: list[dict], analysis: Analysis) -> None:
    levels = analysis.levels
    if levels is None or levels.empty:
        return
    times = _ny(analysis.candles.index)
    for _, level in levels.iterrows():
        shapes.append(
            {
                "type": "line",
                "x0": _ny(pd.DatetimeIndex([level["available_from"]]))[0],
                "x1": times[-1],
                "y0": level["price"],
                "y1": level["price"],
                "line": {"color": COLOURS["level"], "width": 1, "dash": "dashdot"},
                "layer": "below",
            }
        )
        notes.append(
            {
                "x": times[-1],
                "y": level["price"],
                "text": level["name"].replace("_", " "),
                "showarrow": False,
                "xanchor": "right",
                "font": {"size": 9, "color": COLOURS["level"]},
            }
        )


def write_html(figure: go.Figure, path: str) -> str:
    """Write a figure to a standalone HTML file."""
    figure.write_html(path, include_plotlyjs="cdn")
    return path
