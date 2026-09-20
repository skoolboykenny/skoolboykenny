"""What a trade actually costs.

A backtest that fills at the mid price and ignores costs will report an edge
that does not survive contact with a broker. The Silver Bullet trades one
minute fair value gaps, where the gap is often only a few times the spread, so
costs are not a rounding error here: they are most of the question.

Three costs are modelled:

**Spread.** Taken from the data where the file carries it, because the real
spread widens exactly when these setups fire. Where it is missing, a fixed
fallback is used and the report says so, so a result is never quietly better
than it should be.

**Slippage.** A limit order fills at its price or not at all, so entries take
no slippage. Stops are market orders and do slip, so they pay it. Treating a
stop as filling exactly at its price is the single most flattering assumption a
backtest can make.

**Commission.** A flat amount per trade, in the account currency, applied on
entry and again on exit.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CostModel:
    """Spread, slippage and commission for one instrument."""

    #: Used only when the data has no spread column of its own.
    fallback_spread: float = 0.00012
    #: One tick of slippage on stops, in price units. 0.00001 is a point on a
    #: five digit forex feed.
    slippage: float = 0.00002
    #: Account currency per trade, charged on entry and on exit.
    commission: float = 0.0
    #: No entries while the spread is worse than this multiple of its median,
    #: matching the risk rules in the project record.
    max_spread_multiple: float = 2.0

    def spread_at(self, candle: pd.Series) -> float:
        """The spread for this candle, from the data if it carries one."""
        value = candle.get("spread")
        if value is None or value != value or value <= 0:
            return self.fallback_spread
        return float(value)

    def entry_price(self, limit: float, direction: str) -> float:
        """A limit order fills at its price. It does not slip.

        The order rests at the gap; if price never reaches it there is no
        fill at all, which the engine handles separately.
        """
        return limit

    def exit_price(self, price: float, direction: str, is_stop: bool) -> float:
        """Where an exit actually fills.

        Stops are market orders and slip against the position. Targets are
        limit orders and fill at their price or not at all.
        """
        if not is_stop:
            return price
        return price - self.slippage if direction == "long" else price + self.slippage

    def cost_of(self, spread: float) -> float:
        """The spread cost of a round trip, in price units.

        Entering long means paying the ask and leaving on the bid, so a round
        trip crosses the spread once. Detectors run on mid prices, so that
        crossing has to be charged explicitly rather than assumed away.
        """
        return spread

    def is_tradeable(self, spread: float, median_spread: float) -> bool:
        """Whether the spread is normal enough to enter on."""
        if median_spread <= 0:
            return True
        return spread <= median_spread * self.max_spread_multiple
