"""Every tunable number in the system.

Detector code must not contain magic numbers. Each detector takes the relevant
block of this config, so a backtest can sweep parameters by building a modified
``Config`` rather than editing code.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

#: Everything is stored in UTC and reasoned about in New York time, because ICT
#: defines sessions and kill zones there.
STORAGE_TZ = "UTC"
MARKET_TZ = "America/New_York"

#: Canonical column names for a candle frame, in order.
OHLC_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class SwingConfig:
    #: A swing high needs ``n`` candles either side with a lower high.
    n: int = 2


@dataclass(frozen=True)
class LiquidityConfig:
    #: Two swings count as "equal" when they sit within this fraction of ATR.
    equal_tolerance_atr: float = 0.10
    #: A sweep must close back inside the pool within this many candles.
    sweep_close_back_within: int = 3
    #: Only the most recent pools are candidates for clustering a new swing
    #: into. Equal highs are a local pattern: two highs at the same price six
    #: months apart are not the same resting orders, and matching against every
    #: pool ever made would also make the pass quadratic.
    equal_highs_lookback_pools: int = 20

    # The three filters below decide what counts as liquidity worth sweeping.
    # Without them every two bar fractal becomes a pool and every wick past it
    # becomes a sweep, which fires roughly ten times a day on a 15 minute
    # chart: far more often than the concept describes. Each threshold is a
    # starting point argued from the definition, not a fitted value, and all
    # three should be re-tuned against hand labels on real data.

    #: A swing only becomes a pool if it is the extreme of this many candles
    #: before it. Liquidity rests above levels that mattered, not above every
    #: local wiggle.
    prominence_lookback: int = 12
    #: A pool cannot be swept until it has stood this many candles. Stops need
    #: time to accumulate behind a level; one that formed twenty minutes ago
    #: has nothing resting on it yet.
    min_pool_age_candles: int = 4
    #: Price must trade this far beyond the pool, as a fraction of ATR, for the
    #: move to have actually run the stops rather than brushed the level.
    min_penetration_atr: float = 0.10


@dataclass(frozen=True)
class DisplacementConfig:
    #: Body must be at least ``body_atr_multiple`` times ATR(atr_period).
    body_atr_multiple: float = 1.5
    atr_period: int = 14
    #: Body must be at least this fraction of the candle's whole range, which is
    #: what "small wicks" means in code.
    min_body_fraction: float = 0.5


@dataclass(frozen=True)
class StructureConfig:
    #: An MSS must follow a sweep no more than this many candles back.
    sweep_lookback: int = 12


@dataclass(frozen=True)
class FVGConfig:
    #: Gap must be at least this multiple of ATR to be worth recording.
    min_gap_atr: float = 0.05
    atr_period: int = 14


@dataclass(frozen=True)
class OrderBlockConfig:
    #: How far back from the displacement candle to look for the last opposing
    #: candle that formed it.
    lookback: int = 5


@dataclass(frozen=True)
class Config:
    swing: SwingConfig = field(default_factory=SwingConfig)
    liquidity: LiquidityConfig = field(default_factory=LiquidityConfig)
    displacement: DisplacementConfig = field(default_factory=DisplacementConfig)
    structure: StructureConfig = field(default_factory=StructureConfig)
    fvg: FVGConfig = field(default_factory=FVGConfig)
    order_block: OrderBlockConfig = field(default_factory=OrderBlockConfig)

    def with_(self, **changes: object) -> "Config":
        """Return a copy with top-level blocks replaced, for parameter sweeps."""
        return replace(self, **changes)  # type: ignore[arg-type]


DEFAULT_CONFIG = Config()
