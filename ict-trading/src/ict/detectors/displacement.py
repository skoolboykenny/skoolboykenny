"""Displacement: the candle that says the move is intent, not drift.

Two tests, both needed. The body has to be large against the ATR that stood
before it, and the body has to be most of the candle's range. The second test
is what "small wicks" means: a huge candle that gave most of it back inside its
own range is indecision, whatever its high-to-low span.
"""

from __future__ import annotations

import pandas as pd

from ..config import DisplacementConfig
from .atr import atr_prior

DISPLACEMENT_COLUMNS = ("time", "direction", "body", "atr", "body_atr", "body_fraction")


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.Series(dtype="datetime64[ns, UTC]"),
            "direction": pd.Series(dtype="object"),
            "body": pd.Series(dtype="float64"),
            "atr": pd.Series(dtype="float64"),
            "body_atr": pd.Series(dtype="float64"),
            "body_fraction": pd.Series(dtype="float64"),
        }
    )


def displacement_mask(
    candles: pd.DataFrame, config: DisplacementConfig | None = None
) -> pd.Series:
    """Boolean mask: which candles displace."""
    config = config or DisplacementConfig()
    if candles.empty:
        return pd.Series(dtype="bool", index=candles.index)

    body = (candles["close"] - candles["open"]).abs()
    span = (candles["high"] - candles["low"]).replace(0.0, pd.NA)
    reference = atr_prior(candles, config.atr_period)

    big_enough = body >= reference * config.body_atr_multiple
    clean_enough = (body / span) >= config.min_body_fraction
    return (big_enough & clean_enough).fillna(False)


def find_displacements(
    candles: pd.DataFrame, config: DisplacementConfig | None = None
) -> pd.DataFrame:
    """Detect displacement candles, with the measurements behind each call."""
    config = config or DisplacementConfig()
    mask = displacement_mask(candles, config)
    if not mask.any():
        return _empty()

    selected = candles.loc[mask]
    body = (selected["close"] - selected["open"]).abs()
    span = (selected["high"] - selected["low"]).replace(0.0, pd.NA)
    reference = atr_prior(candles, config.atr_period).loc[mask]

    return pd.DataFrame(
        {
            "time": selected.index,
            "direction": [
                "up" if close >= open_ else "down"
                for open_, close in zip(selected["open"], selected["close"])
            ],
            "body": body.to_numpy(),
            "atr": reference.to_numpy(),
            "body_atr": (body / reference).to_numpy(),
            "body_fraction": (body / span).astype("float64").to_numpy(),
        }
    ).reset_index(drop=True)[list(DISPLACEMENT_COLUMNS)]
