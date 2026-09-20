"""Liquidity pools and the sweeps that take them.

A pool is resting stop orders: the highs above which buy stops sit, the lows
below which sell stops sit. One swing is a pool. Several swings at the same
price, within a tolerance, are a better one, because equal highs are the most
advertised stops on the chart.

A sweep is price trading *through* a pool on the wick and closing back inside
within a few candles. Trading through and staying through is a break, not a
sweep, and the distinction is the whole point: the sweep is the one that
suggests the move was about taking the stops rather than going somewhere.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import DisplacementConfig, LiquidityConfig
from ._scan import NOT_FOUND, PriceScanner
from .atr import atr
from .swings import find_swings


def _scanner(candles: pd.DataFrame) -> PriceScanner:
    return PriceScanner(
        candles["high"].to_numpy(),
        candles["low"].to_numpy(),
        candles["close"].to_numpy(),
    )

POOL_COLUMNS = (
    "cluster",
    "price",
    "side",
    "created_at",
    "touches",
    "swept_at",
    "is_equal_highs",
)
SWEEP_COLUMNS = ("time", "pool_price", "side", "extreme", "closed_back_at")


def _empty_pools() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cluster": pd.Series(dtype="int64"),
            "price": pd.Series(dtype="float64"),
            "side": pd.Series(dtype="object"),
            "created_at": pd.Series(dtype="datetime64[ns, UTC]"),
            "touches": pd.Series(dtype="int64"),
            "swept_at": pd.Series(dtype="datetime64[ns, UTC]"),
            "is_equal_highs": pd.Series(dtype="bool"),
        }
    )


def _empty_sweeps() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.Series(dtype="datetime64[ns, UTC]"),
            "pool_price": pd.Series(dtype="float64"),
            "side": pd.Series(dtype="object"),
            "extreme": pd.Series(dtype="float64"),
            "closed_back_at": pd.Series(dtype="datetime64[ns, UTC]"),
        }
    )


def find_pools(
    candles: pd.DataFrame,
    swings: pd.DataFrame | None = None,
    config: LiquidityConfig | None = None,
    atr_period: int = DisplacementConfig().atr_period,
) -> pd.DataFrame:
    """Cluster swings into liquidity pools and mark which have been swept.

    ``side`` is ``"buy"`` for pools above price (swing highs, where buy stops
    rest) and ``"sell"`` for pools below. ``is_equal_highs`` marks a pool built
    from more than one swing, which is the stronger draw.

    One row is emitted per *state* of a pool, not per pool. When a later swing
    joins a cluster the pool gets wider and gains a touch, so a new row is
    emitted with that swing's confirmation as its ``created_at``; earlier rows
    for the same ``cluster`` stay as they were.

    That versioning is what makes the output safe to read at a point in time.
    Carrying one mutable row per cluster would push its ``created_at`` forward
    every time it was extended, so a pool formed in March and extended in April
    would look, to any "what did I know then" filter, as though it did not
    exist in March. Use :func:`unswept` to collapse the versions back to the
    state that held at a given moment.
    """
    config = config or LiquidityConfig()
    if swings is None:
        swings = find_swings(candles)
    if swings.empty:
        return _empty_pools()

    atr_series = atr(candles, atr_period)

    rows: list[dict] = []
    for kind, side in (("high", "buy"), ("low", "sell")):
        selected = swings.loc[swings["kind"] == kind]
        if selected.empty:
            continue

        # Look the ATR up for every swing at once: doing it per swing costs
        # more than the clustering it feeds.
        reference = atr_series.reindex(selected["time"]).to_numpy()
        tolerances = np.nan_to_num(reference, nan=0.0) * config.equal_tolerance_atr
        swing_prices = selected["price"].to_numpy()
        confirmations = selected["confirmed_at"].to_numpy()
        lookback = max(config.equal_highs_lookback_pools, 1)

        open_pools: list[dict] = []
        for price, confirmed, tolerance in zip(
            swing_prices, confirmations, tolerances
        ):
            swing = {"price": price, "confirmed_at": confirmed}
            match = next(
                (
                    pool
                    for pool in reversed(open_pools[-lookback:])
                    if abs(pool["price"] - swing["price"]) <= tolerance
                ),
                None,
            )
            if match is None:
                match = {
                    "cluster": len(rows) + len(open_pools),
                    "price": float(swing["price"]),
                    "side": side,
                    "created_at": swing["confirmed_at"],
                    "touches": 1,
                }
                open_pools.append(match)
            else:
                # The pool sits at the extreme of its members: that is the
                # price the stops are actually beyond.
                match["price"] = (
                    max(match["price"], float(swing["price"]))
                    if side == "buy"
                    else min(match["price"], float(swing["price"]))
                )
                match["touches"] += 1
                match["created_at"] = swing["confirmed_at"]
            # Snapshot the pool as it now stands. Earlier snapshots keep their
            # own created_at, so the history stays readable at any point.
            rows.append(dict(match))

    if not rows:
        return _empty_pools()

    pools = pd.DataFrame(rows)
    pools["is_equal_highs"] = pools["touches"] > 1
    pools["swept_at"] = _first_violation(candles, pools)
    return pools.sort_values("created_at").reset_index(drop=True)[list(POOL_COLUMNS)]


def _first_violation(candles: pd.DataFrame, pools: pd.DataFrame) -> pd.Series:
    """For each pool, the first time price traded beyond it after creation."""
    scanner = _scanner(candles)
    index = candles.index
    created = index.searchsorted(pools["created_at"].to_numpy(), side="right")
    prices = pools["price"].to_numpy()
    buy_side = (pools["side"] == "buy").to_numpy()

    stamps = []
    for start, price, is_buy in zip(created, prices, buy_side):
        hit = scanner.first_traded_beyond(int(start), float(price), bool(is_buy))
        stamps.append(index[hit] if hit != NOT_FOUND else pd.NaT)
    return pd.Series(stamps, index=pools.index, dtype="datetime64[ns, UTC]")


def unswept(pools: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Pools that exist at ``now`` and have not yet been taken.

    This is what the draw on liquidity is chosen from. Because `find_pools`
    emits one row per state, this also collapses each cluster to the newest
    state that had been reached by ``now``: the pool as it actually stood.
    """
    now = pd.Timestamp(now)
    if pools.empty:
        return pools
    existing = pools["created_at"] <= now
    intact = pools["swept_at"].isna() | (pools["swept_at"] > now)
    live = pools.loc[existing & intact]
    if live.empty or "cluster" not in live.columns:
        return live.reset_index(drop=True)
    newest = live.sort_values("created_at").groupby("cluster", as_index=False).last()
    return newest.reset_index(drop=True)[list(POOL_COLUMNS)]


def find_sweeps(
    candles: pd.DataFrame,
    pools: pd.DataFrame | None = None,
    config: LiquidityConfig | None = None,
) -> pd.DataFrame:
    """Detect liquidity sweeps: wick beyond a pool, close back inside.

    The sweep is timed at the candle that traded beyond the pool, not at the
    candle that closed back, because that is the extreme a later stop is placed
    beyond. ``closed_back_at`` records when it was confirmed.
    """
    config = config or LiquidityConfig()
    if pools is None:
        pools = find_pools(candles, config=config)
    if pools.empty or candles.empty:
        return _empty_sweeps()

    window = config.sweep_close_back_within
    scanner = _scanner(candles)
    index = candles.index
    highs, lows, closes = scanner.highs, scanner.lows, scanner.closes

    created = index.searchsorted(pools["created_at"].to_numpy(), side="right")
    prices = pools["price"].to_numpy()
    sides = pools["side"].to_numpy()
    rows = []

    for start_at, price, side in zip(created, prices, sides):
        buy_side = side == "buy"
        breached = scanner.first_traded_beyond(int(start_at), float(price), buy_side)
        if breached == NOT_FOUND:
            continue

        # Only candles inside the close-back window can confirm the sweep.
        end = min(breached + window + 1, len(index))
        segment_closes = closes[breached:end]
        inside = segment_closes < price if buy_side else segment_closes > price
        confirmations = np.flatnonzero(inside)
        if not len(confirmations):
            continue

        confirm_at = breached + int(confirmations[0])
        span = slice(breached, confirm_at + 1)
        rows.append(
            {
                "time": index[breached],
                "pool_price": float(price),
                "side": side,
                "extreme": float(
                    highs[span].max() if buy_side else lows[span].min()
                ),
                "closed_back_at": index[confirm_at],
            }
        )

    if not rows:
        return _empty_sweeps()
    return (
        pd.DataFrame(rows)
        # Successive states of one cluster can describe the same breach, so
        # the same sweep is only reported once.
        .drop_duplicates(subset=["time", "side", "pool_price"])
        .sort_values("time")
        .reset_index(drop=True)[list(SWEEP_COLUMNS)]
    )
