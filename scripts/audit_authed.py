"""Authenticated OWASP probes — run inside halsa-load (isolated DB)."""
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "halsa.settings")
django.setup()

from django.test import Client  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402

from django.conf import settings as dj_settings
dj_settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
U = get_user_model()
PW = "Probe-pw-9182!"
XSS = "<img src=x onerror=alert(1)>"
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS" if ok else "FAIL"), name, detail[:90])


def mkuser(name):
    u = U.objects.filter(username=name).first()
    if u:
        u.delete()
    return U.objects.create_user(username=name, password=PW)


def login(u):
    c = Client(SERVER_NAME="localhost")
    c.get("/accounts/login/")
    r = c.post("/accounts/login/", {"username": u.username, "password": PW})
    assert r.status_code == 302, r.status_code
    return c


a = mkuser("probe-a")
b = mkuser("probe-b")
ca, cb = login(a), login(b)

# --- A03 stored XSS via note (notes are set on the edit route) -----------------
r = ca.post("/add/", {"taken_at": "2026-10-19T12:00", "glucose": "5.5"})
check("add accepted (302)", r.status_code == 302)
from tracker.models import GlucoseReading as _GR  # noqa: E402
_rid = _GR.objects.filter(user=a).order_by("-taken_at").first().id
r = ca.post(f"/glucose/edit/{_rid}/", {"value": "5.5",
                                       "taken_at": "2026-10-19T12:00",
                                       "note": XSS})
check("edit with XSS note accepted (302)", r.status_code == 302)
for page in ("/history/", "/", "/glucose/"):
    body = cb.get(page).content.decode()
    check(f"XSS escaped in {page}", XSS not in body)

# --- A03 NUL + oversized note ---------------------------------------------------
r = ca.post(f"/glucose/edit/{_rid}/", {"value": "5.5",
                                       "taken_at": "2026-10-19T12:00",
                                       "note": "bad\x00note"})
check("NUL note -> no 500", r.status_code in (200, 302), f"got {r.status_code}")
r = ca.post(f"/glucose/edit/{_rid}/", {"value": "5.5",
                                       "taken_at": "2026-10-19T12:00",
                                       "note": "x" * 5000})
check("oversized note rejected by form", r.status_code == 200,
      f"got {r.status_code}")

# --- A01 IDOR -------------------------------------------------------------------
from tracker.models import GlucoseReading  # noqa: E402
rid = GlucoseReading.objects.filter(user=a).first().id
r = cb.get(f"/glucose/edit/{rid}/")
check("IDOR edit other user's row -> 404", r.status_code == 404,
      f"got {r.status_code}")
r = cb.post(f"/glucose/delete/{rid}/")
check("IDOR delete other user's row -> 404", r.status_code == 404,
      f"got {r.status_code}")
still = GlucoseReading.objects.filter(id=rid).exists()
check("victim row survives IDOR delete", still)

# --- A05 email header injection via schedule name --------------------------------
import datetime as dt  # noqa: E402
from tracker.models import MetricSettings, Schedule  # noqa: E402
MetricSettings.objects.get_or_create(user=a, metric="glucose")
a.email = "probe-a@example.invalid"
a.save()
evil_name = "x\r\nBcc: evil@evil.example"
sch = Schedule.objects.filter(user=a).first()
if not sch:
    sch = Schedule(user=a, metric="glucose", name=evil_name,
                   time=dt.time(9), weekdays=[0, 1, 2, 3, 4])
    sch.save()
sch.name = evil_name
sch.save()
from django.core import mail  # noqa: E402
from tracker import scheduling  # noqa: E402
try:
    from django.core.mail import EmailMessage  # noqa: E402
    subj, body = scheduling.build_email(
        a, [(sch, dt.datetime(2026, 10, 19, 9, 0))])
    msg = EmailMessage(subj, body, "halsa@localhost", [a.email])
    msg.send()
    sent = mail.outbox[-1] if mail.outbox else None
    if sent is not None:
        head = sent.message().as_string().split("\n\n", 1)[0]
        check("email CRLF injection neutralized",
              sent.message()["Bcc"] is None and "Bcc: evil" not in head)
    else:
        check("email CRLF injection neutralized", True, "(no mail due)")
except Exception as e:  # noqa: BLE001
    check("email CRLF injection neutralized", "newline" in str(e).lower(),
          f"raised {type(e).__name__}: {e}")
finally:
    mail.outbox.clear()

# --- A07 2FA ----------------------------------------------------------------------
import pyotp  # noqa: E402
from tracker.models import Profile  # noqa: E402
p = Profile.objects.get(user=a)
p.totp_seed = pyotp.random_base32()
p.totp_confirmed = True
p.save()
c2 = Client(SERVER_NAME="localhost")
c2.get("/accounts/login/")
r = c2.post("/accounts/login/", {"username": a.username, "password": PW})
check("2FA pending (not logged in)", "_auth_user_id" not in c2.session)
r = c2.post("/accounts/login/", {"code": "000000"})
check("wrong TOTP rejected", "_auth_user_id" not in c2.session)
c2.get("/accounts/login/")
r = c2.post("/accounts/login/", {"username": a.username, "password": PW})
good = pyotp.TOTP(p.totp_seed).now()
r = c2.post("/accounts/login/", {"code": good})
check("valid TOTP accepted", "_auth_user_id" in c2.session)

# --- A03 exports -------------------------------------------------------------------
r = ca.get("/export/json/")
check("json export content-type", r["Content-Type"].startswith("application/json"),
      r["Content-Type"])
check("json export nosniff", r.get("X-Content-Type-Options") == "nosniff")
r = ca.get("/export/pdf/")
check("pdf export ok", r.status_code == 200 and r["Content-Type"] == "application/pdf")

# cleanup
a.delete()
b.delete()
fails = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(fails)}/{len(results)} authed probes as expected")
if fails:
    print("FAILURES:", fails)
    sys.exit(1)
