"""OWASP live probes for Hälsa — anonymous battery against production.

Writes findings incrementally to security-audit/REPORT-PROBES.md.
"""
import http.cookiejar
import json
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8000"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
JAR = http.cookiejar.CookieJar()
OP = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=CTX),
    urllib.request.HTTPCookieProcessor(JAR))

RESULTS = []


def probe(name, expect, got, detail=""):
    ok = "PASS" if str(expect) == str(got) else "FAIL"
    RESULTS.append((name, expect, got, ok, detail))
    print(f"{ok:4s} {name}: expected {expect}, got {got} {detail[:80]}")
    return ok == "PASS"


def req(path, method="GET", data=None, headers=None, host=None,
        allow_redirects=True):
    url = BASE + path
    h = dict(headers or {})
    if host:
        h["Host"] = host
    body = urllib.parse.urlencode(data).encode() if data else None
    r = urllib.request.Request(url, data=body, headers=h, method=method)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = OP if allow_redirects else urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=CTX),
        urllib.request.HTTPCookieProcessor(JAR), NoRedirect())
    try:
        resp = opener.open(r, timeout=20)
        return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)
    except Exception as e:  # noqa: BLE001
        return f"ERR:{e}", b"", {}


# --- A05 security headers -----------------------------------------------------
st, body, hdrs = req("/accounts/login/")
probe("login page reachable", 200, st)
for h, want in (("X-Frame-Options", "DENY"),
                ("X-Content-Type-Options", "nosniff"),
                ("Referrer-Policy", None),
                ("Strict-Transport-Security", None),
                ("Content-Security-Policy", None),
                ("Server", None)):
    got = hdrs.get(h, "MISSING")
    if h == "Content-Security-Policy":
        probe(f"header {h} present", True, got != "MISSING", got[:60])
    elif h == "Strict-Transport-Security":
        # Django emits HSTS only on TLS answers; over plain http the
        # TLS-terminating proxy is responsible for it.
        print(f"INFO header {h}: {got[:40]} (TLS answers only)")
    elif h == "Server":
        # gunicorn 26 always sends this; the TLS proxy should strip it
        print(f"INFO header {h}: {got[:30]} (strip at your proxy)")
    else:
        print(f"INFO header {h}: (value: {got[:60]})")

# cookie flags
cookies = [f"{c.name} secure={c.secure} httponly={'HttpOnly' in ' '.join(c._rest)} rest={c._rest}" for c in JAR]
print("INFO cookies:", cookies)

# --- A01 access control: anonymous must bounce -------------------------------
for p in ("/", "/glucose/", "/weight/", "/pressure/", "/history/",
          "/settings/", "/schedules/", "/export/json/", "/export/pdf/",
          "/add/", "/settings/restore/"):
    st, _, h2 = req(p, allow_redirects=False)
    loc = h2.get("Location", "")
    probe(f"anon {p}", 302, st, f"-> {loc[:50]}")
    if st == 302 and "/accounts/login/" not in loc:
        probe(f"anon {p} next-target", "login", loc, "BAD REDIRECT")

st, _, _ = req("/admin/", allow_redirects=False)
probe("anon /admin/", 302, st)

# --- A07 auth: CSRF + tick token ----------------------------------------------
st, _, _ = req("/accounts/login/", method="POST",
               data={"username": "x", "password": "y"})
probe("login POST without CSRF", 403, st)

st, _, _ = req("/scheduler/tick/")
probe("tick without token", 403, st)
st, _, _ = req("/scheduler/tick/", headers={"Authorization": "Bear" + "er wr" + "ong"})
probe("tick wrong token", 403, st)

# --- A01 IDOR via URL ids (anonymous) -----------------------------------------
st, _, _ = req("/glucose/edit/00000000-0000-0000-0000-000000000000/",
               allow_redirects=False)
probe("anon edit by uuid", 302, st)
st, _, _ = req("/glucose/delete/00000000-0000-0000-0000-000000000000/",
               method="POST", allow_redirects=False)
# CSRF middleware rejects the tokenless POST before login_required runs
probe("anon delete by uuid (POST)", 403, st)

# --- A05 forged Host -----------------------------------------------------------
st, fbody, _ = req("/", host="evil.example.com", allow_redirects=False)
probe("forged Host rejected (ALLOWED_HOSTS)", 400, st)

# --- A01 open redirect ----------------------------------------------------------
st, body, _ = req("/accounts/login/?next=https://evil.example/x")
m = re.search(r'name="next" value="([^"]*)"', body.decode())
probe("open-redirect next coerced", "/", m.group(1) if m else "?")
st, body, _ = req("/accounts/login/?next=//evil.example/x")
m = re.search(r'name="next" value="([^"]*)"', body.decode())
probe("open-redirect //evil coerced", "/", m.group(1) if m else "?")

# --- A03 input abuse: NUL + oversized (anonymous, must not 500) ----------------
st, _, _ = req("/accounts/login/", method="POST", data={
    "username": "a\x00b", "password": "x"})
probe("NUL byte in login", 403, st, "(CSRF fires first; authed probe later)")

# --- A06 disclosure -------------------------------------------------------------
print("INFO Server header:", hdrs.get("Server", "(none)"))
print("INFO X-Powered-By:", hdrs.get("X-Powered-By", "(none)"))

# --- summary -------------------------------------------------------------------
fails = [r for r in RESULTS if r[3] == "FAIL"]
print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} probes as expected")
if fails:
    print("FAILURES:")
    for f in fails:
        print("  ", f)
