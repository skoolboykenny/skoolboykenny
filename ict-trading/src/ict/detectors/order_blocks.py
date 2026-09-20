"""Order blocks: the last opposing candle before the move that broke structure.

The definition is deliberately narrow. Not every down candle before a rally is
an order block. It has to be the *last* one before a displacement leg, and that
leg has to break structure. Without the structure break, the zone is just a
candle that happened to be there.

The block's zone is the candle's whole range. Its mean threshold, the 50% line
ICT treats as the point of interest, is recorded alongside it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import DisplacementConfig, OrderBlockConfig
from ._scan import NOT_FOUND, PriceScanner
from .displacement import displacement_mask
from .structure import find_breaks_of_structure

ORDER_BLOCK_COLUMNS = (
    "time",
    "direction",
    "top",
    "bottom",
    "mean_threshold",
    "break_time",
    "mitigated_at",
)


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.Series(dtype="datetime64[ns, UTC]"),
            "direction": pd.Series(dtype="object"),
            "top": pd.Series(dtype="float64"),
            "bottom": pd.Series(dtype="float64"),
            "mean_threshold": pd.Series(dtype="float64"),
            "break_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "mitigated_at": pd.Series(dtype="datetime64[ns, UTC]"),
        }
    )


def find_order_blocks(
    candles: pd.DataFrame,
    breaks: pd.DataFrame | None = None,
    config: OrderBlockConfig | None = None,
    displacement: DisplacementConfig | None = None,
) -> pd.DataFrame:
    """Detect order blocks behind each break of structure.

    Walking back from the break, the first displacement candle is the leg, and
    the last opposing candle before it is the block.
    """
    config = config or OrderBlockConfig()
    displacement = displacement or DisplacementConfig()
    if breaks is None:
        breaks = find_breaks_of_structure(candles)
    if breaks.empty or candles.empty:
        return _empty()

    displaces = displacement_mask(candles, displacement).to_numpy()
    opens = candles["open"].to_numpy()
    closes = candles["close"].to_numpy()
    positions = {stamp: i for i, stamp in enumerate(candles.index)}

    rows = []
    for _, event in breaks.iterrows():
        end = positions.get(event["time"])
        if end is None:
            continue
        bullish = event["direction"] == "up"

        # The displacement leg that caused the break, at or just before it.
        leg = None
        for i in range(end, max(end - config.lookback, -1), -1):
            leg_direction_matches = (
                closes[i] > opens[i] if bullish else closes[i] < opens[i]
            )
            if displaces[i] and leg_direction_matches:
                leg = i
                break
        if leg is None:
            continue

        # The last candle before the leg that went the other way.
        block = None
        for i in range(leg - 1, max(leg - 1 - config.lookback, -1), -1):
            opposing = closes[i] < opens[i] if bullish else closes[i] > opens[i]
            if opposing:
                block = i
                break
        if block is None:
            continue

        top = float(candles["high"].iloc[block])
        bottom = float(candles["low"].iloc[block])
        rows.append(
            {
                "time": candles.index[block],
                "direction": "bullish" if bullish else "bearish",
                "top": top,
                "bottom": bottom,
                "mean_threshold": (top + bottom) / 2.0,
                "break_time": event["time"],
            }
        )

    if not rows:
        return _empty()

    blocks = pd.DataFrame(rows).drop_duplicates(subset=["time", "direction"])
    blocks["mitigated_at"] = _first_retest(candles, blocks)
    return blocks.sort_values("time").reset_index(drop=True)[
        list(ORDER_BLOCK_COLUMNS)
    ]


def _first_retest(candles: pd.DataFrame, blocks: pd.DataFrame) -> pd.Series:
    """First return into each block after the break that created it."""
    scanner = PriceScanner(
        candles["high"].to_numpy(),
        candles["low"].to_numpy(),
        candles["close"].to_numpy(),
    )
    index = candles.index
    starts = index.searchsorted(blocks["break_time"].to_numpy(), side="right")

    stamps = []
    for start, top, bottom in zip(
        starts, blocks["top"].to_numpy(), blocks["bottom"].to_numpy()
    ):
        hit = scanner.first_overlap(int(start), float(bottom), float(top))
        stamps.append(index[hit] if hit != NOT_FOUND else pd.NaT)
    return pd.Series(stamps, index=blocks.index, dtype="datetime64[ns, UTC]")
