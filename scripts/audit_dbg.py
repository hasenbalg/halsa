import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "halsa.settings")
django.setup()

from django.test import Client  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402

U = get_user_model()
PW = "Probe-pw-9182!"
XSS = "<img src=x onerror=alert(1)>"

u = U.objects.filter(username="dbg-xss").first() or U.objects.create_user(
    username="dbg-xss", password=PW)
c = Client(SERVER_NAME="localhost")
c.get("/accounts/login/")
c.post("/accounts/login/", {"username": u.username, "password": PW})
r = c.post("/add/", {"taken_at": "2026-10-19T12:00", "glucose": "5.5",
                     "note": XSS})
print("add status:", r.status_code)
from tracker.models import GlucoseReading  # noqa: E402
row = GlucoseReading.objects.filter(user=u).order_by("-taken_at").first()
print("stored note:", repr(row.note))
r = c.get("/history/")
body = r.content.decode()
i = body.find("onerror")
print("history ctx:", repr(body[max(0, i - 120):i + 40]) if i >= 0 else "not rendered")
r = c.get("/")
body = r.content.decode()
i = body.find("onerror")
print("dashboard ctx:", repr(body[max(0, i - 120):i + 40]) if i >= 0 else "not rendered")

# oversized note limit
print("note field:", GlucoseReading._meta.get_field("note"))
big = "x" * 5000
r = c.post("/add/", {"taken_at": "2026-10-19T12:05", "glucose": "5.6",
                     "note": big})
row2 = GlucoseReading.objects.filter(user=u).order_by("-taken_at").first()
print("big note saved:", len(row2.note or ""))

# email CRLF structure
from django.conf import settings as dj_settings  # noqa: E402
dj_settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
import datetime as dt  # noqa: E402
from django.core import mail  # noqa: E402
from django.core.mail import EmailMessage  # noqa: E402
from tracker import scheduling  # noqa: E402
from tracker.models import Schedule  # noqa: E402
u.email = "dbg@example.invalid"
u.save()
sch = Schedule.objects.filter(user=u).first() or Schedule(
    user=u, metric="glucose", name="x\r\nBcc: evil@evil.example",
    time=dt.time(9), weekdays=[0])
sch.name = "x\r\nBcc: evil@evil.example"
sch.save()
subj, msg_body = scheduling.build_email(u, [(sch, dt.datetime(2026, 10, 19, 9, 0))])
m = EmailMessage(subj, msg_body, "halsa@localhost", [u.email])
m.send()
sent = mail.outbox[-1]
raw = sent.message().as_string()
head = raw.split("\n\n", 1)[0]
print("Bcc header parsed:", sent.message()["Bcc"])
print("Bcc in header block:", "Bcc: evil" in head)
print("Bcc in body (inert text):", "Bcc: evil" in raw.split("\n\n", 1)[1])

# cleanup
u.delete()
Schedule.objects.filter(name__startswith="x\r\n").delete()
