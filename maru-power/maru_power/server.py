"""HTTP JSON API + static app. Standard library only.

    python -m maru_power.server            # http://localhost:8080
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import fnb
from .service import AppError, Service

STATIC = Path(__file__).resolve().parent.parent / "static"
COOKIE = "mp_session"

ROUTES = []


def route(method, pattern, auth=True):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), auth, fn))
        return fn
    return deco


@route("POST", "/api/signup", auth=False)
def _signup(s, uid, b): return {"_session": s.signup(b.get("name"), b.get("email"), b.get("password"))}
@route("POST", "/api/login", auth=False)
def _login(s, uid, b): return {"_session": s.login(b.get("email"), b.get("password"))}
@route("GET", "/api/me")
def _me(s, uid, b): return s.me(uid)
@route("PUT", "/api/me")
def _profile(s, uid, b): return s.update_profile(uid, b)
@route("GET", "/api/dashboard")
def _dash(s, uid, b): return s.dashboard(uid)

@route("POST", "/api/bank/link")
def _bl(s, uid, b): return s.bank_start(uid, b.get("account_number"), b.get("holder"))
@route("POST", "/api/bank/confirm")
def _bc(s, uid, b): return s.bank_confirm(uid, b.get("otp"))
@route("DELETE", "/api/bank")
def _bd(s, uid, b): s.bank_remove(uid); return {"ok": True}

@route("POST", "/api/meters/verify")
def _mv(s, uid, b): return s.verify_meter(b.get("number"))
@route("GET", "/api/meters")
def _ml(s, uid, b): return s.meters(uid)
@route("POST", "/api/meters")
def _ma(s, uid, b): return s.add_meter(uid, b.get("number"), b.get("nickname"))
@route("GET", r"/api/meters/(\d+)")
def _mg(s, uid, b, mid): return s.meter(uid, int(mid))
@route("PUT", r"/api/meters/(\d+)")
def _mr(s, uid, b, mid): return s.rename_meter(uid, int(mid), b.get("nickname"))
@route("DELETE", r"/api/meters/(\d+)")
def _md(s, uid, b, mid): s.remove_meter(uid, int(mid)); return {"ok": True}
@route("POST", r"/api/meters/(\d+)/share")
def _ms(s, uid, b, mid): return s.share_meter(uid, int(mid), b.get("email"))
@route("DELETE", r"/api/meters/(\d+)/share/(\d+)")
def _mu(s, uid, b, mid, member): return s.unshare_meter(uid, int(mid), int(member))
@route("POST", r"/api/meters/(\d+)/readings")
def _rd(s, uid, b, mid): return s.add_reading(uid, int(mid), b.get("kwh"))

@route("POST", "/api/quote")
def _q(s, uid, b): return s.quote(uid, int(b.get("meter_id") or 0), b.get("amount"))
@route("POST", "/api/buy")
def _buy(s, uid, b): return s.buy(uid, int(b.get("meter_id") or 0), b.get("amount"), b.get("source"))
@route("POST", "/api/wallet/topup")
def _top(s, uid, b): return s.topup(uid, b.get("amount"))
@route("POST", r"/api/payments/(\d+)/approve")
def _ap(s, uid, b, pid): return s.approve(uid, int(pid), b.get("otp"))
@route("GET", "/api/payments")
def _pl(s, uid, b): return s.payments(uid)
@route("GET", "/api/purchases")
def _pu(s, uid, b): return s.purchases(uid)
@route("POST", "/api/purchases")
def _pr(s, uid, b): return s.record_purchase(uid, int(b.get("meter_id") or 0), b.get("amount"), b.get("kwh"), b.get("token"))

@route("GET", "/api/rules")
def _rg(s, uid, b): return s.rules(uid)
@route("PUT", "/api/rules")
def _rs(s, uid, b): return s.set_rules(uid, b)
@route("GET", "/api/notifications")
def _ng(s, uid, b): return s.notifications(uid)
@route("POST", "/api/notifications/read")
def _nr(s, uid, b): s.mark_read(uid); return {"ok": True}


def make_handler(svc: Service, secure_cookie: bool):
    class H(BaseHTTPRequestHandler):
        server_version = "MaruPower"

        def log_message(self, *a):
            if os.environ.get("MP_LOG"):
                super().log_message(*a)

        def _token(self):
            c = SimpleCookie(self.headers.get("Cookie", ""))
            return c[COOKIE].value if COOKIE in c else None

        def _send(self, status, body: bytes, ctype, extra=()):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, obj, extra=()):
            self._send(status, json.dumps(obj).encode(), "application/json", extra)

        def _api(self, method):
            path = self.path.split("?")[0]
            if method != "GET" and self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._json(415, {"error": "Send JSON"})
            body = {}
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                if n > 64_000:
                    return self._json(413, {"error": "Too large"})
                try:
                    body = json.loads(self.rfile.read(n))
                except ValueError:
                    return self._json(400, {"error": "Bad JSON"})
            if path == "/api/logout" and method == "POST":
                svc.logout(self._token())
                return self._json(200, {"ok": True}, [("Set-Cookie", f"{COOKIE}=; Path=/; Max-Age=0")])
            for m, rx, auth, fn in ROUTES:
                mt = rx.match(path)
                if m != method or not mt:
                    continue
                uid = svc.user_for(self._token())
                if auth and not uid:
                    return self._json(401, {"error": "Please sign in"})
                try:
                    with svc.lock:
                        out = fn(svc, uid, body, *mt.groups())
                except AppError as e:
                    return self._json(e.status, {"error": str(e)})
                except (ValueError, TypeError):
                    return self._json(400, {"error": "Check the details you entered"})
                if isinstance(out, dict) and "_session" in out:
                    flags = "; Secure" if secure_cookie else ""
                    cookie = f"{COOKIE}={out['_session']}; Path=/; HttpOnly; SameSite=Strict; Max-Age={14*86400}{flags}"
                    return self._json(200, {"ok": True}, [("Set-Cookie", cookie)])
                return self._json(200, out)
            return self._json(404, {"error": "Not found"})

        def _static(self):
            rel = self.path.split("?")[0].lstrip("/") or "index.html"
            f = (STATIC / rel).resolve()
            if not str(f).startswith(str(STATIC)) or not f.is_file():
                f = STATIC / "index.html"
            self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")

        def do_GET(self):
            return self._api("GET") if self.path.startswith("/api/") else self._static()

        def do_POST(self): self._api("POST")
        def do_PUT(self): self._api("PUT")
        def do_DELETE(self): self._api("DELETE")

    return H


def build(db_path=None, fnb_client=None, port=0, secure_cookie=False, clock=None):
    kw = {"clock": clock} if clock else {}
    svc = Service(db_path or ":memory:", fnb_client or fnb.from_env(), **kw)
    return ThreadingHTTPServer(("127.0.0.1" if port == 0 else "0.0.0.0", port), make_handler(svc, secure_cookie)), svc


def main():
    port = int(os.environ.get("PORT", 8080))
    srv, _ = build(os.environ.get("MP_DB", "maru_power.db"), port=port, secure_cookie=bool(os.environ.get("MP_SECURE")))
    print(f"Maru Power on http://localhost:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
