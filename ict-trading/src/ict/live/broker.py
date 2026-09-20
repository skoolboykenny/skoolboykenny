"""Placing and managing orders through OANDA.

The backtest's :class:`~ict.backtest.broker.Broker` simulates fills. This one
sends the same orders to a real account. Both take the same
:class:`~ict.backtest.strategy.Setup`, so the thing being paper traded is the
thing that was backtested, not a re-implementation of it.

**Every order carries its stop and target with it.** OANDA attaches them at
fill time, in the same request, so a position is never naked, not even for the
milliseconds between a fill and a follow up call. If the process dies the
instant after a fill, the broker still holds the stop. That property is worth
more than any feature in this module.

Rounding matters here in a way it does not in a backtest. OANDA rejects a
price with more precision than the instrument allows, so prices are rounded to
the instrument's own precision before they are sent, and units are whole.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from ..backtest.strategy import Setup
from ..data.oanda import OandaClient, OandaError


@dataclass(frozen=True)
class Instrument:
    """What the broker says about an instrument, which decides rounding."""

    name: str
    display_precision: int = 5
    minimum_trade_size: float = 1.0
    maximum_trade_size: float = 100_000_000.0
    margin_rate: float = 0.02

    def round_price(self, price: float) -> str:
        """A price at the instrument's own precision, as OANDA wants it."""
        quantum = Decimal(1).scaleb(-self.display_precision)
        return str(Decimal(str(price)).quantize(quantum, rounding=ROUND_HALF_UP))

    def round_units(self, units: float) -> int:
        """Whole units, never rounded up past the maximum."""
        clipped = min(abs(units), self.maximum_trade_size)
        return int(clipped)


@dataclass
class PlacedOrder:
    """What came back from placing an order."""

    order_id: str
    setup: Setup
    units: int
    placed_at: pd.Timestamp
    raw: dict


class LiveBroker:
    """The order side of the OANDA account.

    Deliberately small. It places, cancels and reports; it makes no decisions.
    Anything that decides lives in the model or the risk manager, which are the
    parts that were tested.
    """

    def __init__(self, client: OandaClient, instrument: str = "EUR_USD") -> None:
        self.client = client
        self.instrument_name = instrument
        self._instrument: Instrument | None = None

    # --- account -----------------------------------------------------------

    def instrument(self) -> Instrument:
        """The instrument's precision and limits, fetched once and kept."""
        if self._instrument is not None:
            return self._instrument
        payload = self.client.get(
            f"/v3/accounts/{self.client.account_id}/instruments",
            params={"instruments": self.instrument_name},
        )
        found = payload.get("instruments") or []
        if not found:
            raise OandaError(f"the account cannot trade {self.instrument_name}")
        spec = found[0]
        self._instrument = Instrument(
            name=spec["name"],
            display_precision=int(spec.get("displayPrecision", 5)),
            minimum_trade_size=float(spec.get("minimumTradeSize", 1)),
            maximum_trade_size=float(spec.get("maximumOrderUnits", 100_000_000)),
            margin_rate=float(spec.get("marginRate", 0.02)),
        )
        return self._instrument

    def account(self) -> dict:
        """Balance, open positions and unrealised profit."""
        payload = self.client.get(f"/v3/accounts/{self.client.account_id}/summary")
        return payload.get("account", {})

    def equity(self) -> float:
        """Net asset value, which is what position sizing must work from.

        Balance alone ignores an open position's unrealised loss, and sizing
        off it means sizing off money that is already gone.
        """
        summary = self.account()
        return float(summary.get("NAV", summary.get("balance", 0.0)))

    def open_trades(self) -> list[dict]:
        payload = self.client.get(f"/v3/accounts/{self.client.account_id}/openTrades")
        return payload.get("trades", [])

    def pending_orders(self) -> list[dict]:
        payload = self.client.get(f"/v3/accounts/{self.client.account_id}/pendingOrders")
        return payload.get("orders", [])

    @property
    def is_idle(self) -> bool:
        """No position and nothing resting, which is when a new setup may go."""
        return not self.open_trades() and not self.pending_orders()

    # --- orders ------------------------------------------------------------

    def place(
        self,
        setup: Setup,
        size: float,
        expires_at: pd.Timestamp | None = None,
        client_tag: str = "",
    ) -> PlacedOrder:
        """Rest a limit order with its stop and target attached.

        ``GTD`` with an expiry rather than ``GTC``: an ICT setup belongs to its
        window, and an order that outlives the window is a different strategy
        wearing the name. The backtest expires orders the same way.
        """
        instrument = self.instrument()
        units = instrument.round_units(size)
        if units < instrument.minimum_trade_size:
            raise OandaError(
                f"size {size:.2f} is below the minimum trade size "
                f"{instrument.minimum_trade_size:.0f}"
            )
        signed = units if setup.direction == "long" else -units

        order: dict = {
            "type": "LIMIT",
            "instrument": instrument.name,
            "units": str(signed),
            "price": instrument.round_price(setup.limit),
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": instrument.round_price(setup.stop)},
            "takeProfitOnFill": {"price": instrument.round_price(setup.target)},
        }
        expiry = expires_at or setup.expires_at
        if expiry is not None:
            order["timeInForce"] = "GTD"
            order["gtdTime"] = pd.Timestamp(expiry).tz_convert("UTC").strftime(
                "%Y-%m-%dT%H:%M:%S.000000000Z"
            )
        else:
            order["timeInForce"] = "GTC"
        if client_tag:
            order["clientExtensions"] = {"tag": client_tag, "comment": setup.reason[:128]}

        payload = self.client.post(
            f"/v3/accounts/{self.client.account_id}/orders", {"order": order}
        )
        created = payload.get("orderCreateTransaction")
        if not created:
            raise OandaError(f"order was not created: {payload}")
        return PlacedOrder(
            order_id=str(created["id"]),
            setup=setup,
            units=units,
            placed_at=pd.Timestamp(created["time"]).tz_convert("UTC"),
            raw=payload,
        )

    def cancel(self, order_id: str) -> dict:
        return self.client.put(
            f"/v3/accounts/{self.client.account_id}/orders/{order_id}/cancel", {}
        )

    def cancel_all(self) -> int:
        """Cancel everything resting. Part of the kill switch."""
        cancelled = 0
        for order in self.pending_orders():
            self.cancel(str(order["id"]))
            cancelled += 1
        return cancelled

    def close_all(self) -> int:
        """Close every open position at market. The other half of the kill switch."""
        closed = 0
        for trade in self.open_trades():
            self.client.put(
                f"/v3/accounts/{self.client.account_id}/trades/{trade['id']}/close",
                {"units": "ALL"},
            )
            closed += 1
        return closed

    def closed_trades_since(self, since: pd.Timestamp) -> list[dict]:
        """Trades that closed after ``since``, for reconciling the journal."""
        payload = self.client.get(
            f"/v3/accounts/{self.client.account_id}/trades",
            params={"state": "CLOSED", "count": 200},
        )
        out = []
        for trade in payload.get("trades", []):
            closed = trade.get("closeTime")
            if closed and pd.Timestamp(closed).tz_convert("UTC") > since:
                out.append(trade)
        return out
