"""A simulated broker: resting orders, open positions and how they fill.

Everything here is resolved bar by bar on closed candles. Two rules keep it
honest.

**A candle's path is unknown.** A one minute candle tells you its open, high,
low and close, not the order it visited them in. When a candle would hit both
the stop and the target, this assumes the stop went first. That is the
pessimistic reading, and it is the right default: the optimistic one turns
losing systems into winning ones on paper.

**An order placed on a candle cannot fill on that candle.** The decision to
place it was made from that candle's close, so the earliest it can be touched
is the next one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .costs import CostModel


@dataclass
class Order:
    """A resting limit order with its stop and target already decided."""

    placed_at: pd.Timestamp
    direction: str  # "long" or "short"
    limit: float
    stop: float
    target: float
    size: float
    expires_at: pd.Timestamp
    reason: str = ""

    @property
    def risk_per_unit(self) -> float:
        return abs(self.limit - self.stop)

    def would_fill(self, candle: pd.Series) -> bool:
        """Did price trade through the limit on this candle?"""
        if self.direction == "long":
            return float(candle["low"]) <= self.limit
        return float(candle["high"]) >= self.limit


@dataclass
class Position:
    """A filled order, with its exit still to come."""

    opened_at: pd.Timestamp
    direction: str
    entry: float
    stop: float
    target: float
    size: float
    spread_paid: float
    reason: str = ""
    partial_taken: bool = False

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop)


@dataclass
class Trade:
    """A closed position, with everything needed to judge it."""

    opened_at: pd.Timestamp
    closed_at: pd.Timestamp
    direction: str
    entry: float
    exit: float
    stop: float
    target: float
    size: float
    reason: str
    outcome: str  # "target", "stop", "expiry", "session_end"
    gross: float
    costs: float

    @property
    def net(self) -> float:
        return self.gross - self.costs

    @property
    def r_multiple(self) -> float:
        """Result as a multiple of the risk taken.

        R is the unit the whole project judges trades in: a strategy is
        compared on expectancy per trade in R, not on currency, so position
        sizing and account size cannot flatter it.
        """
        risk = abs(self.entry - self.stop) * self.size
        return self.net / risk if risk else 0.0


@dataclass
class Broker:
    """Holds the resting order and the open position, and resolves both."""

    costs: CostModel
    order: Order | None = None
    position: Position | None = None
    trades: list[Trade] = field(default_factory=list)

    @property
    def is_idle(self) -> bool:
        return self.order is None and self.position is None

    def place(self, order: Order) -> None:
        """Rest an order. Only one at a time, by design."""
        if not self.is_idle:
            raise RuntimeError("cannot place an order while one is live")
        self.order = order

    def cancel(self) -> None:
        self.order = None

    def on_candle(self, stamp: pd.Timestamp, candle: pd.Series) -> None:
        """Advance one candle: resolve the position first, then the order.

        Order matters. A position closing on this candle frees the broker, but
        the order that replaces it must not also fill on the same candle.
        """
        if self.position is not None:
            self._resolve_position(stamp, candle)
            return

        if self.order is not None:
            self._resolve_order(stamp, candle)

    def _resolve_order(self, stamp: pd.Timestamp, candle: pd.Series) -> None:
        order = self.order
        assert order is not None

        if stamp <= order.placed_at:
            return  # cannot fill on the candle it was placed from

        if stamp >= order.expires_at:
            self.order = None
            return

        if not order.would_fill(candle):
            return

        spread = self.costs.spread_at(candle)
        self.position = Position(
            opened_at=stamp,
            direction=order.direction,
            entry=self.costs.entry_price(order.limit, order.direction),
            stop=order.stop,
            target=order.target,
            size=order.size,
            spread_paid=spread,
            reason=order.reason,
        )
        self.order = None

    def _resolve_position(self, stamp: pd.Timestamp, candle: pd.Series) -> None:
        position = self.position
        assert position is not None
        if stamp <= position.opened_at:
            return

        high = float(candle["high"])
        low = float(candle["low"])
        long = position.direction == "long"

        hit_stop = low <= position.stop if long else high >= position.stop
        hit_target = high >= position.target if long else low <= position.target

        if hit_stop:
            # Pessimistic: when both are touched on one candle, the stop wins.
            self._close(stamp, candle, position.stop, "stop")
        elif hit_target:
            self._close(stamp, candle, position.target, "target")

    def close_now(self, stamp: pd.Timestamp, candle: pd.Series, outcome: str) -> None:
        """Flatten at the close, for a session or backtest ending."""
        if self.position is not None:
            self._close(stamp, candle, float(candle["close"]), outcome)
        self.order = None

    def _close(
        self,
        stamp: pd.Timestamp,
        candle: pd.Series,
        price: float,
        outcome: str,
    ) -> None:
        position = self.position
        assert position is not None

        is_stop = outcome == "stop"
        fill = self.costs.exit_price(price, position.direction, is_stop)
        direction = 1.0 if position.direction == "long" else -1.0
        gross = (fill - position.entry) * direction * position.size

        spread_cost = self.costs.cost_of(position.spread_paid) * position.size
        costs = spread_cost + self.costs.commission * 2.0

        self.trades.append(
            Trade(
                opened_at=position.opened_at,
                closed_at=stamp,
                direction=position.direction,
                entry=position.entry,
                exit=fill,
                stop=position.stop,
                target=position.target,
                size=position.size,
                reason=position.reason,
                outcome=outcome,
                gross=gross,
                costs=costs,
            )
        )
        self.position = None
