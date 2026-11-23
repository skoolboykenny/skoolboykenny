"""FNB bank connection.

Customers link their own FNB account and approve each debit. Funds move from
their account straight to the merchant; Maru Power never holds card details.

`SimulatedFnb` is used until real FNB API credentials are configured. `HttpFnb`
is the shape of the real integration; its endpoint paths are placeholders to be
replaced with the ones in FNB's partner documentation once access is granted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import urllib.request
from dataclasses import dataclass


class FnbError(Exception):
    pass


@dataclass
class Challenge:
    ref: str            # FNB's reference for the consent or payment
    status: str         # pending | approved | declined
    dev_otp: str | None = None  # only the simulator returns this


class FnbClient:
    def start_link(self, account_number: str, holder: str) -> Challenge: ...
    def confirm_link(self, ref: str, otp: str) -> str: ...          # returns consent id
    def start_debit(self, consent: str, amount_cents: int, reference: str) -> Challenge: ...
    def confirm_debit(self, ref: str, otp: str) -> str: ...         # returns FNB transaction id
    def revoke(self, consent: str) -> None: ...


class SimulatedFnb(FnbClient):
    """In-memory FNB. OTPs are returned to the caller so the flow can be tested.

    Account numbers ending in 0 are treated as having insufficient funds.
    """

    def __init__(self):
        self._pending: dict[str, dict] = {}
        self._consents: dict[str, str] = {}

    def _challenge(self, **data) -> Challenge:
        ref = "SIM" + secrets.token_hex(6).upper()
        otp = f"{secrets.randbelow(10**6):06d}"
        self._pending[ref] = {**data, "otp": otp, "tries": 0}
        return Challenge(ref, "pending", otp)

    def _check(self, ref: str, otp: str) -> dict:
        p = self._pending.get(ref)
        if not p:
            raise FnbError("Unknown or expired request")
        p["tries"] += 1
        if p["tries"] > 3:
            self._pending.pop(ref, None)
            raise FnbError("Too many attempts. Start again.")
        if not hmac.compare_digest(p["otp"], str(otp).strip()):
            raise FnbError("Incorrect OTP")
        return self._pending.pop(ref)

    def start_link(self, account_number, holder):
        if not (account_number.isdigit() and 9 <= len(account_number) <= 13):
            raise FnbError("FNB account numbers are 9 to 13 digits")
        return self._challenge(kind="link", account=account_number)

    def confirm_link(self, ref, otp):
        p = self._check(ref, otp)
        consent = "CNS" + secrets.token_hex(8).upper()
        self._consents[consent] = p["account"]
        return consent

    def start_debit(self, consent, amount_cents, reference):
        account = self._consents.get(consent)
        if account is None:
            raise FnbError("Bank link is no longer valid. Link your FNB account again.")
        if account.endswith("0"):
            raise FnbError("Insufficient funds in FNB account")
        return self._challenge(kind="debit", amount=amount_cents)

    def confirm_debit(self, ref, otp):
        self._check(ref, otp)
        return "FNBTX" + secrets.token_hex(6).upper()

    def revoke(self, consent):
        self._consents.pop(consent, None)


class HttpFnb(FnbClient):
    """Real FNB integration (OAuth client credentials + signed requests).

    Configure with FNB_BASE_URL, FNB_CLIENT_ID, FNB_CLIENT_SECRET.
    Paths below are placeholders pending FNB's partner API documentation.
    """

    def __init__(self, base_url: str, client_id: str, client_secret: str):
        self.base = base_url.rstrip("/")
        self.client_id = client_id
        self.secret = client_secret

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        sig = hmac.new(self.secret.encode(), data, hashlib.sha256).hexdigest()
        req = urllib.request.Request(
            self.base + path, data=data, method="POST",
            headers={"Content-Type": "application/json", "X-Client-Id": self.client_id, "X-Signature": sig},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            raise FnbError(f"FNB is unavailable: {e}") from e

    def start_link(self, account_number, holder):
        r = self._post("/consents", {"accountNumber": account_number, "holder": holder})
        return Challenge(r["consentRequestId"], r.get("status", "pending"))

    def confirm_link(self, ref, otp):
        return self._post(f"/consents/{ref}/authorise", {"otp": otp})["consentId"]

    def start_debit(self, consent, amount_cents, reference):
        r = self._post("/payments", {"consentId": consent, "amount": amount_cents, "currency": "BWP", "reference": reference})
        return Challenge(r["paymentId"], r.get("status", "pending"))

    def confirm_debit(self, ref, otp):
        return self._post(f"/payments/{ref}/authorise", {"otp": otp})["transactionId"]

    def revoke(self, consent):
        self._post(f"/consents/{consent}/revoke", {})


def from_env() -> FnbClient:
    if os.environ.get("FNB_CLIENT_ID"):
        return HttpFnb(os.environ["FNB_BASE_URL"], os.environ["FNB_CLIENT_ID"], os.environ["FNB_CLIENT_SECRET"])
    return SimulatedFnb()
