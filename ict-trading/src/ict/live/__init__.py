"""Live and paper trading: the broker adapter and the loop that drives it.

Nothing in this package is reachable from a backtest, and nothing in the
backtest imports it. The separation is deliberate: the tested code must not
change shape because a live path needed something.
"""

from .broker import Instrument, LiveBroker, PlacedOrder
from .runner import CandleBuilder, Guards, Halt, LiveRunner

__all__ = [
    "CandleBuilder",
    "Guards",
    "Halt",
    "Instrument",
    "LiveBroker",
    "LiveRunner",
    "PlacedOrder",
]
