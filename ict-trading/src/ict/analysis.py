"""Run every detector over one timeframe and collect the results.

This is the seam the plots and, later, the strategy engine both sit on. It runs
detectors in dependency order, threading each one's output into the next so
swings are computed once rather than five times.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import DEFAULT_CONFIG, Config
from .detectors.displacement import find_displacements
from .detectors.fvg import find_fvgs
from .detectors.levels import session_levels
from .detectors.liquidity import find_pools, find_sweeps
from .detectors.order_blocks import find_order_blocks
from .detectors.structure import find_breaks_of_structure, find_market_structure_shifts
from .detectors.swings import find_swings


@dataclass
class Analysis:
    """Everything the detectors found on one frame of candles."""

    candles: pd.DataFrame
    timeframe: str
    swings: pd.DataFrame
    pools: pd.DataFrame
    sweeps: pd.DataFrame
    displacements: pd.DataFrame
    breaks: pd.DataFrame
    shifts: pd.DataFrame
    fvgs: pd.DataFrame
    order_blocks: pd.DataFrame
    levels: pd.DataFrame = field(default_factory=pd.DataFrame)

    def counts(self) -> dict[str, int]:
        """How many of each thing was found, for a quick sanity read."""
        return {
            "candles": len(self.candles),
            "swings": len(self.swings),
            "pools": len(self.pools),
            "sweeps": len(self.sweeps),
            "displacements": len(self.displacements),
            "breaks": len(self.breaks),
            "shifts": len(self.shifts),
            "fvgs": len(self.fvgs),
            "order_blocks": len(self.order_blocks),
            "levels": len(self.levels),
        }


def analyse(
    candles: pd.DataFrame,
    timeframe: str = "1m",
    config: Config | None = None,
    with_levels: bool = False,
) -> Analysis:
    """Run every detector over ``candles``.

    Session levels are only meaningful on 1 minute data, so they are opt in.
    """
    config = config or DEFAULT_CONFIG

    swings = find_swings(candles, config.swing)
    pools = find_pools(
        candles, swings=swings, config=config.liquidity, atr_period=config.fvg.atr_period
    )
    sweeps = find_sweeps(candles, pools=pools, config=config.liquidity)
    displacements = find_displacements(candles, config.displacement)
    breaks = find_breaks_of_structure(candles, swings=swings)
    shifts = find_market_structure_shifts(
        candles,
        sweeps=sweeps,
        swings=swings,
        config=config.structure,
        displacement=config.displacement,
    )
    fvgs = find_fvgs(candles, config.fvg)
    order_blocks = find_order_blocks(
        candles, breaks=breaks, config=config.order_block, displacement=config.displacement
    )
    levels = session_levels(candles) if with_levels else pd.DataFrame()

    return Analysis(
        candles=candles,
        timeframe=timeframe,
        swings=swings,
        pools=pools,
        sweeps=sweeps,
        displacements=displacements,
        breaks=breaks,
        shifts=shifts,
        fvgs=fvgs,
        order_blocks=order_blocks,
        levels=levels,
    )


def analyse_stack(
    frames: dict[str, pd.DataFrame], config: Config | None = None
) -> dict[str, Analysis]:
    """Analyse every timeframe in a stack. Levels come from the 1 minute frame."""
    return {
        timeframe: analyse(
            frame, timeframe=timeframe, config=config, with_levels=timeframe == "1m"
        )
        for timeframe, frame in frames.items()
    }
