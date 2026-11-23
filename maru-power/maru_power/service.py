"""Business logic and storage for Maru Power (SQLite)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from .fnb import FnbClient, FnbError
from .vend import SimulatedVendor, VendError

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL,
  wallet_cents INTEGER NOT NULL DEFAULT 0, household_size INTEGER, home_type TEXT,
  created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bank_links (
  user_id INTEGER PRIMARY KEY, account_mask TEXT NOT NULL, holder TEXT NOT NULL,
  consent TEXT, pending_ref TEXT, status TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meters (
  id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL, nickname TEXT, customer_name TEXT,
  address TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meter_access (
  meter_id INTEGER NOT NULL, user_id INTEGER NOT NULL, role TEXT NOT NULL,
  PRIMARY KEY (meter_id, user_id));
CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY, meter_id INTEGER NOT NULL, user_id INTEGER NOT NULL, kwh REAL NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL, meter_id INTEGER,
  amount_cents INTEGER NOT NULL, status TEXT NOT NULL, fnb_ref TEXT, fnb_tx TEXT,
  error TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS purchases (
  id INTEGER PRIMARY KEY, meter_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
  amount_cents INTEGER NOT NULL, kwh REAL NOT NULL, token TEXT, vat_cents INTEGER,
  reference TEXT, source TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS rules (
  user_id INTEGER PRIMARY KEY, low_kwh REAL NOT NULL DEFAULT 20,
  autobuy INTEGER NOT NULL DEFAULT 0, autobuy_cents INTEGER NOT NULL DEFAULT 10000, meter_id INTEGER);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
  read INTEGER NOT NULL DEFAULT 0, at REAL NOT NULL);
"""

SESSION_DAYS = 14
DAY = 86400


class AppError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _hash_pw(pw: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return salt.hex() + "$" + h.hex()


def _check_pw(pw: str, stored: str) -> bool:
    salt, _ = stored.split("$")
    return hmac.compare_digest(_hash_pw(pw, bytes.fromhex(salt)), stored)


def _money(v) -> int:
    try:
        cents = round(float(v) * 100)
    except (TypeError, ValueError):
        raise AppError("Enter an amount in Pula")
    if cents <= 0:
        raise AppError("Amount must be more than zero")
    if cents > 500_000:
        raise AppError("Maximum is P5,000 per transaction")
    return cents


def _month_start(now: float) -> float:
    d = datetime.fromtimestamp(now, timezone.utc)
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


class Service:
    def __init__(self, path: str, fnb: FnbClient, vendor=None, clock=time.time):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()
        self.fnb = fnb
        self.vendor = vendor or SimulatedVendor()
        self.now = clock

    # -- helpers ---------------------------------------------------------
    def q(self, sql, *a):
        return [dict(r) for r in self.db.execute(sql, a).fetchall()]

    def one(self, sql, *a):
        r = self.db.execute(sql, a).fetchone()
        return dict(r) if r else None

    def notify(self, uid, kind, text):
        self.db.execute("INSERT INTO notifications(user_id,kind,text,at) VALUES(?,?,?,?)", (uid, kind, text, self.now()))

    def _role(self, uid, meter_id):
        r = self.one("SELECT role FROM meter_access WHERE meter_id=? AND user_id=?", meter_id, uid)
        if not r:
            raise AppError("Meter not found", 404)
        return r["role"]

    # -- accounts --------------------------------------------------------
    def signup(self, name, email, pw):
        name, email = (name or "").strip(), (email or "").strip().lower()
        if not name or "@" not in email:
            raise AppError("Enter your name and a valid email")
        if len(pw or "") < 8:
            raise AppError("Password must be at least 8 characters")
        with self.lock:
            if self.one("SELECT 1 FROM users WHERE email=?", email):
                raise AppError("An account with this email already exists")
            cur = self.db.execute("INSERT INTO users(name,email,pw,created) VALUES(?,?,?,?)", (name, email, _hash_pw(pw), self.now()))
            uid = cur.lastrowid
            self.db.execute("INSERT INTO rules(user_id) VALUES(?)", (uid,))
        return self._session(uid)

    def login(self, email, pw):
        u = self.one("SELECT id,pw FROM users WHERE email=?", (email or "").strip().lower())
        if not u or not _check_pw(pw or "", u["pw"]):
            raise AppError("Email or password is incorrect", 401)
        return self._session(u["id"])

    def _session(self, uid):
        tok = secrets.token_urlsafe(32)
        self.db.execute("INSERT INTO sessions VALUES(?,?,?)", (tok, uid, self.now() + SESSION_DAYS * DAY))
        return tok

    def user_for(self, tok):
        if not tok:
            return None
        s = self.one("SELECT user_id FROM sessions WHERE token=? AND expires>?", tok, self.now())
        return s["user_id"] if s else None

    def logout(self, tok):
        self.db.execute("DELETE FROM sessions WHERE token=?", (tok,))

    def me(self, uid):
        u = self.one("SELECT id,name,email,wallet_cents,household_size,home_type FROM users WHERE id=?", uid)
        u["bank"] = self.one("SELECT account_mask,holder,status FROM bank_links WHERE user_id=?", uid)
        u["unread"] = self.one("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND read=0", uid)["n"]
        return u

    def update_profile(self, uid, data):
        hs = data.get("household_size")
        if hs is not None and not (isinstance(hs, int) and 1 <= hs <= 30):
            raise AppError("Household size must be 1 to 30")
        self.db.execute("UPDATE users SET household_size=COALESCE(?,household_size), home_type=COALESCE(?,home_type), name=COALESCE(NULLIF(?,''),name) WHERE id=?",
                        (hs, data.get("home_type"), (data.get("name") or "").strip(), uid))
        return self.me(uid)

    # -- FNB bank link ---------------------------------------------------
    def bank_start(self, uid, account, holder):
        account = (account or "").replace(" ", "")
        try:
            ch = self.fnb.start_link(account, holder or "")
        except FnbError as e:
            raise AppError(str(e))
        self.db.execute("INSERT OR REPLACE INTO bank_links VALUES(?,?,?,?,?,?,?)",
                        (uid, "••••" + account[-4:], holder or "", None, ch.ref, "pending", self.now()))
        return {"status": "otp_required", "dev_otp": ch.dev_otp}

    def bank_confirm(self, uid, otp):
        link = self.one("SELECT * FROM bank_links WHERE user_id=?", uid)
        if not link or link["status"] != "pending":
            raise AppError("No bank link in progress")
        try:
            consent = self.fnb.confirm_link(link["pending_ref"], otp)
        except FnbError as e:
            raise AppError(str(e))
        self.db.execute("UPDATE bank_links SET consent=?, pending_ref=NULL, status='active' WHERE user_id=?", (consent, uid))
        self.notify(uid, "bank", f"FNB account {link['account_mask']} linked.")
        return self.me(uid)["bank"]

    def bank_remove(self, uid):
        link = self.one("SELECT consent FROM bank_links WHERE user_id=?", uid)
        if link and link["consent"]:
            try:
                self.fnb.revoke(link["consent"])
            except FnbError:
                pass
        self.db.execute("DELETE FROM bank_links WHERE user_id=?", (uid,))

    # -- meters ----------------------------------------------------------
    def verify_meter(self, number):
        try:
            c = self.vendor.confirm_customer((number or "").strip())
        except VendError as e:
            raise AppError(str(e))
        return {"number": c.meter, "customer_name": c.name, "address": c.address}

    def add_meter(self, uid, number, nickname):
        c = self.verify_meter(number)
        with self.lock:
            m = self.one("SELECT id FROM meters WHERE number=?", c["number"])
            if m:
                if self.one("SELECT 1 FROM meter_access WHERE meter_id=?", m["id"]):
                    raise AppError("This meter is already registered. Ask its owner to share it with you.")
                mid = m["id"]
            else:
                mid = self.db.execute("INSERT INTO meters(number,nickname,customer_name,address,created) VALUES(?,?,?,?,?)",
                                      (c["number"], nickname or "Home", c["customer_name"], c["address"], self.now())).lastrowid
            self.db.execute("INSERT INTO meter_access VALUES(?,?, 'owner')", (mid, uid))
        return self.meter(uid, mid)

    def meters(self, uid):
        return [self.meter(uid, r["meter_id"]) for r in self.q("SELECT meter_id FROM meter_access WHERE user_id=? ORDER BY meter_id", uid)]

    def meter(self, uid, mid):
        role = self._role(uid, mid)
        m = self.one("SELECT * FROM meters WHERE id=?", mid)
        m["role"] = role
        m.update(self._estimate(mid))
        if role == "owner":
            m["members"] = self.q("SELECT u.id,u.name,u.email,a.role FROM meter_access a JOIN users u ON u.id=a.user_id WHERE a.meter_id=? ORDER BY a.role DESC", mid)
        return m

    def rename_meter(self, uid, mid, nickname):
        if self._role(uid, mid) != "owner":
            raise AppError("Only the meter owner can do that", 403)
        self.db.execute("UPDATE meters SET nickname=? WHERE id=?", ((nickname or "").strip()[:40] or "Home", mid))
        return self.meter(uid, mid)

    def remove_meter(self, uid, mid):
        role = self._role(uid, mid)
        if role == "owner":
            self.db.execute("DELETE FROM meter_access WHERE meter_id=?", (mid,))
        else:
            self.db.execute("DELETE FROM meter_access WHERE meter_id=? AND user_id=?", (mid, uid))

    def share_meter(self, uid, mid, email):
        if self._role(uid, mid) != "owner":
            raise AppError("Only the meter owner can share it", 403)
        u = self.one("SELECT id,name FROM users WHERE email=?", (email or "").strip().lower())
        if not u:
            raise AppError("No Maru Power account uses that email. Ask them to sign up first.")
        self.db.execute("INSERT OR IGNORE INTO meter_access VALUES(?,?,'member')", (mid, u["id"]))
        m = self.one("SELECT nickname FROM meters WHERE id=?", mid)
        self.notify(u["id"], "share", f"You were given access to meter “{m['nickname']}”.")
        return self.meter(uid, mid)

    def unshare_meter(self, uid, mid, member_id):
        if self._role(uid, mid) != "owner":
            raise AppError("Only the meter owner can do that", 403)
        self.db.execute("DELETE FROM meter_access WHERE meter_id=? AND user_id=? AND role='member'", (mid, member_id))
        return self.meter(uid, mid)

    def add_reading(self, uid, mid, kwh):
        self._role(uid, mid)
        try:
            kwh = float(kwh)
        except (TypeError, ValueError):
            raise AppError("Enter the units shown on your meter")
        if not 0 <= kwh < 100000:
            raise AppError("That reading doesn't look right")
        self.db.execute("INSERT INTO readings(meter_id,user_id,kwh,at) VALUES(?,?,?,?)", (mid, uid, kwh, self.now()))
        self._check_low(mid)
        return self.meter(uid, mid)

    # -- estimates -------------------------------------------------------
    def _daily_use(self, mid):
        """kWh per day, from readings and purchases between them; else from purchases."""
        rs = self.q("SELECT kwh,at FROM readings WHERE meter_id=? ORDER BY at", mid)
        if len(rs) >= 2:
            a, b = rs[0], rs[-1]
            bought = self.one("SELECT COALESCE(SUM(kwh),0) s FROM purchases WHERE meter_id=? AND at>? AND at<=?", mid, a["at"], b["at"])["s"]
            days = (b["at"] - a["at"]) / DAY
            if days >= 1:
                return max(0.0, (a["kwh"] + bought - b["kwh"]) / days), "readings"
        ps = self.q("SELECT kwh,at FROM purchases WHERE meter_id=? AND at>? ORDER BY at", mid, self.now() - 60 * DAY)
        if len(ps) >= 2:
            days = max(1.0, (self.now() - ps[0]["at"]) / DAY)
            return sum(p["kwh"] for p in ps[:-1]) / days, "purchases"
        return None, None

    def _estimate(self, mid):
        now = self.now()
        last = self.one("SELECT kwh,at FROM readings WHERE meter_id=? ORDER BY at DESC LIMIT 1", mid)
        per_day, basis = self._daily_use(mid)
        balance = None
        if last:
            since = self.one("SELECT COALESCE(SUM(kwh),0) s FROM purchases WHERE meter_id=? AND at>?", mid, last["at"])["s"]
            balance = last["kwh"] + since - (per_day or 0) * (now - last["at"]) / DAY
        elif per_day is not None:
            lp = self.one("SELECT kwh,at FROM purchases WHERE meter_id=? ORDER BY at DESC LIMIT 1", mid)
            balance = lp["kwh"] - per_day * (now - lp["at"]) / DAY
        balance = None if balance is None else max(0.0, round(balance, 1))
        days = round(balance / per_day, 1) if balance is not None and per_day else None
        return {"balance_kwh": balance, "daily_kwh": None if per_day is None else round(per_day, 2),
                "days_left": days, "estimate_basis": basis, "verified": bool(last and now - last["at"] < 2 * DAY)}

    def _kwh_this_month(self, mid):
        return self.one("SELECT COALESCE(SUM(kwh),0) s FROM purchases WHERE meter_id=? AND at>=?", mid, _month_start(self.now()))["s"]

    def _check_low(self, mid):
        est = self._estimate(mid)
        if est["balance_kwh"] is None:
            return
        m = self.one("SELECT nickname FROM meters WHERE id=?", mid)
        for a in self.q("SELECT a.user_id, r.low_kwh, r.autobuy, r.autobuy_cents, r.meter_id FROM meter_access a JOIN rules r ON r.user_id=a.user_id WHERE a.meter_id=?", mid):
            if est["balance_kwh"] > a["low_kwh"]:
                continue
            recent = self.one("SELECT 1 FROM notifications WHERE user_id=? AND kind='low' AND at>?", a["user_id"], self.now() - DAY)
            if recent:
                continue
            if a["autobuy"] and a["meter_id"] == mid:
                try:
                    p = self.buy(a["user_id"], mid, a["autobuy_cents"] / 100, "wallet")
                    self.notify(a["user_id"], "autobuy", f"Auto-bought P{a['autobuy_cents']/100:.2f} for “{m['nickname']}”. Token {p['purchase']['token']}")
                    continue
                except AppError as e:
                    self.notify(a["user_id"], "low", f"Auto-buy for “{m['nickname']}” failed: {e}")
                    continue
            self.notify(a["user_id"], "low", f"“{m['nickname']}” is low: about {est['balance_kwh']} kWh left.")

    # -- buying ----------------------------------------------------------
    def quote(self, uid, mid, amount):
        self._role(uid, mid)
        from .vend import units_for
        cents = _money(amount)
        return {"amount_cents": cents, "kwh": units_for(cents, self._kwh_this_month(mid))}

    def buy(self, uid, mid, amount, source):
        """Start a purchase. Wallet purchases complete now; FNB ones need OTP approval."""
        self._role(uid, mid)
        cents = _money(amount)
        if source == "wallet":
            with self.lock:
                cur = self.db.execute("UPDATE users SET wallet_cents=wallet_cents-? WHERE id=? AND wallet_cents>=?", (cents, uid, cents))
                if cur.rowcount != 1:
                    raise AppError("Not enough in your wallet")
                pid = self.db.execute("INSERT INTO payments(user_id,kind,meter_id,amount_cents,status,created) VALUES(?,?,?,?,?,?)",
                                      (uid, "vend", mid, cents, "paid", self.now())).lastrowid
            return self._fulfil(pid)
        if source == "fnb":
            return self._start_fnb(uid, "vend", cents, mid)
        raise AppError("Choose wallet or FNB")

    def topup(self, uid, amount):
        return self._start_fnb(uid, "topup", _money(amount), None)

    def _start_fnb(self, uid, kind, cents, mid):
        link = self.one("SELECT consent,status FROM bank_links WHERE user_id=?", uid)
        if not link or link["status"] != "active":
            raise AppError("Link your FNB account first")
        pid = self.db.execute("INSERT INTO payments(user_id,kind,meter_id,amount_cents,status,created) VALUES(?,?,?,?,?,?)",
                              (uid, kind, mid, cents, "pending", self.now())).lastrowid
        try:
            ch = self.fnb.start_debit(link["consent"], cents, f"MARUPOWER{pid}")
        except FnbError as e:
            self.db.execute("UPDATE payments SET status='failed', error=? WHERE id=?", (str(e), pid))
            raise AppError(str(e))
        self.db.execute("UPDATE payments SET fnb_ref=? WHERE id=?", (ch.ref, pid))
        return {"payment_id": pid, "status": "otp_required", "dev_otp": ch.dev_otp}

    def approve(self, uid, pid, otp):
        with self.lock:
            p = self.one("SELECT * FROM payments WHERE id=? AND user_id=?", pid, uid)
            if not p:
                raise AppError("Payment not found", 404)
            if p["status"] != "pending":
                raise AppError("This payment is no longer waiting for approval")
            try:
                tx = self.fnb.confirm_debit(p["fnb_ref"], otp)
            except FnbError as e:
                if "attempts" in str(e) or "Unknown" in str(e):
                    self.db.execute("UPDATE payments SET status='failed', error=? WHERE id=?", (str(e), pid))
                raise AppError(str(e))
            self.db.execute("UPDATE payments SET status='paid', fnb_tx=? WHERE id=?", (tx, pid))
            if p["kind"] == "topup":
                self.db.execute("UPDATE users SET wallet_cents=wallet_cents+? WHERE id=?", (p["amount_cents"], uid))
                self.notify(uid, "topup", f"Wallet topped up with P{p['amount_cents']/100:.2f} from FNB.")
                return {"payment_id": pid, "status": "paid", "wallet_cents": self.me(uid)["wallet_cents"]}
        return self._fulfil(pid)

    def _fulfil(self, pid):
        p = self.one("SELECT * FROM payments WHERE id=?", pid)
        m = self.one("SELECT * FROM meters WHERE id=?", p["meter_id"])
        try:
            v = self.vendor.vend(m["number"], p["amount_cents"], self._kwh_this_month(m["id"]))
        except VendError as e:
            # Money was taken but no token: refund to wallet so the customer is never out of pocket.
            self.db.execute("UPDATE payments SET status='refunded', error=? WHERE id=?", (str(e), pid))
            self.db.execute("UPDATE users SET wallet_cents=wallet_cents+? WHERE id=?", (p["amount_cents"], p["user_id"]))
            self.notify(p["user_id"], "refund", f"Token could not be issued ({e}). P{p['amount_cents']/100:.2f} returned to your wallet.")
            raise AppError(f"{e}. Your money was returned to your wallet.", 502)
        src = "fnb" if p["fnb_tx"] else "wallet"
        purchase_id = self.db.execute(
            "INSERT INTO purchases(meter_id,user_id,amount_cents,kwh,token,vat_cents,reference,source,at) VALUES(?,?,?,?,?,?,?,?,?)",
            (m["id"], p["user_id"], p["amount_cents"], v.kwh, v.token, v.vat_cents, v.reference, src, self.now())).lastrowid
        self.db.execute("UPDATE payments SET status='complete' WHERE id=?", (pid,))
        tok = " ".join(v.token[i:i + 4] for i in range(0, 20, 4))
        self.notify(p["user_id"], "purchase", f"{v.kwh} kWh for “{m['nickname']}”. Token: {tok}")
        return {"payment_id": pid, "status": "complete", "purchase": self.purchase(p["user_id"], purchase_id)}

    def record_purchase(self, uid, mid, amount, kwh, token):
        """Log a purchase made elsewhere (bank app, shop) so estimates stay accurate."""
        self._role(uid, mid)
        cents = _money(amount)
        try:
            kwh = float(kwh)
        except (TypeError, ValueError):
            raise AppError("Enter the units you received")
        pid = self.db.execute("INSERT INTO purchases(meter_id,user_id,amount_cents,kwh,token,source,at) VALUES(?,?,?,?,?,?,?)",
                              (mid, uid, cents, kwh, (token or "").replace(" ", "") or None, "manual", self.now())).lastrowid
        return self.purchase(uid, pid)

    def purchase(self, uid, pid):
        p = self.one("SELECT p.*, m.nickname, m.number FROM purchases p JOIN meters m ON m.id=p.meter_id WHERE p.id=?", pid)
        if not p:
            raise AppError("Purchase not found", 404)
        self._role(uid, p["meter_id"])
        return p

    def purchases(self, uid, limit=50):
        return self.q("""SELECT p.*, m.nickname, m.number, u.name buyer FROM purchases p
                         JOIN meters m ON m.id=p.meter_id JOIN users u ON u.id=p.user_id
                         JOIN meter_access a ON a.meter_id=p.meter_id AND a.user_id=?
                         ORDER BY p.at DESC LIMIT ?""", uid, limit)

    def payments(self, uid):
        return self.q("SELECT id,kind,meter_id,amount_cents,status,fnb_tx,error,created FROM payments WHERE user_id=? ORDER BY id DESC LIMIT 50", uid)

    # -- rules & notifications ------------------------------------------
    def rules(self, uid):
        return self.one("SELECT low_kwh,autobuy,autobuy_cents,meter_id FROM rules WHERE user_id=?", uid)

    def set_rules(self, uid, d):
        low = float(d.get("low_kwh", 20))
        cents = _money(d.get("autobuy_amount", 100))
        mid = d.get("meter_id")
        if mid is not None:
            self._role(uid, int(mid))
        self.db.execute("UPDATE rules SET low_kwh=?, autobuy=?, autobuy_cents=?, meter_id=? WHERE user_id=?",
                        (max(0.0, low), 1 if d.get("autobuy") else 0, cents, mid, uid))
        return self.rules(uid)

    def notifications(self, uid):
        return self.q("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50", uid)

    def mark_read(self, uid):
        self.db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (uid,))

    # -- dashboard -------------------------------------------------------
    def dashboard(self, uid):
        now = self.now()
        ms = _month_start(now)
        meters = self.meters(uid)
        for m in meters:
            self._check_low(m["id"])
        ids = [m["id"] for m in meters] or [-1]
        ph = ",".join("?" * len(ids))
        month = self.one(f"SELECT COALESCE(SUM(amount_cents),0) c, COALESCE(SUM(kwh),0) k, COUNT(*) n FROM purchases WHERE meter_id IN ({ph}) AND at>=?", *ids, ms)
        start = datetime.fromtimestamp(ms, timezone.utc)
        trend = []
        for i in range(5, -1, -1):
            a = (start.replace(day=1) - timedelta(days=31 * i)).replace(day=1)
            b = (a + timedelta(days=32)).replace(day=1)
            r = self.one(f"SELECT COALESCE(SUM(kwh),0) k, COALESCE(SUM(amount_cents),0) c FROM purchases WHERE meter_id IN ({ph}) AND at>=? AND at<?", *ids, a.timestamp(), b.timestamp())
            trend.append({"month": a.strftime("%b"), "kwh": round(r["k"], 1), "cents": r["c"]})
        u = self.me(uid)
        score = None
        daily = [m["daily_kwh"] for m in meters if m["daily_kwh"] is not None]
        if daily:
            bench = 4.0 * (u["household_size"] or 3)  # kWh/day typical for household size
            score = max(0, min(100, round(100 - (sum(daily) / bench - 0.6) * 100)))
        days = [m["days_left"] for m in meters if m["days_left"] is not None]
        return {"user": u, "meters": meters, "month_cents": month["c"], "month_kwh": round(month["k"], 1),
                "month_count": month["n"], "days_left": min(days) if days else None,
                "efficiency": score, "trend": trend, "recent": self.purchases(uid, 5)}
