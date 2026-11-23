"""Electricity vending: meter lookup and token issue.

`SimulatedVendor` stands in for BPC until the XMLVend connection from Maru Vend
is wired in. It generates random 20-digit tokens; they will not load on a real meter.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

# Illustrative domestic tariff (thebe per kWh, VAT inclusive). Set to BPC's
# current published tariff before going live.
TARIFF_BLOCKS = [(200, int(os.environ.get("TARIFF_BLOCK1", 120))), (None, int(os.environ.get("TARIFF_BLOCK2", 160)))]
VAT_RATE = 0.14


class VendError(Exception):
    pass


@dataclass
class Customer:
    meter: str
    name: str
    address: str


@dataclass
class Vend:
    token: str
    kwh: float
    vat_cents: int
    reference: str


def units_for(amount_cents: int, kwh_bought_this_month: float) -> float:
    """kWh an amount buys, respecting the monthly block already used."""
    left, kwh, used = amount_cents, 0.0, kwh_bought_this_month
    for limit, price in TARIFF_BLOCKS:
        room = float("inf") if limit is None else max(0.0, limit - used)
        if room <= 0:
            continue
        take = min(room, left / price)
        kwh += take
        left -= take * price
        used += take
        if left <= 0.0001:
            break
    return round(kwh, 1)


def valid_meter(number: str) -> bool:
    return number.isdigit() and len(number) in (11, 13)


class SimulatedVendor:
    def confirm_customer(self, meter: str) -> Customer:
        if not valid_meter(meter):
            raise VendError("Meter numbers are 11 or 13 digits")
        if meter.startswith("0000"):
            raise VendError("Meter not found at BPC")
        return Customer(meter, "Prepaid customer", f"Plot {int(meter[-4:])}, Gaborone")

    def vend(self, meter: str, amount_cents: int, kwh_this_month: float) -> Vend:
        self.confirm_customer(meter)
        if amount_cents < 1000:
            raise VendError("Minimum purchase is P10")
        token = "".join(str(secrets.randbelow(10)) for _ in range(20))
        vat = round(amount_cents * VAT_RATE / (1 + VAT_RATE))
        return Vend(token, units_for(amount_cents, kwh_this_month), vat, "MP" + secrets.token_hex(5).upper())
