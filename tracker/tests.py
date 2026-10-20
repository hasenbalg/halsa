import json
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from . import scheduling, units as U
from .models import (
    BloodPressureReading,
    GlucoseReading,
    Metric,
    MetricSettings,
    OverdueNotice,
    Profile,
    Schedule,
    WeightReading,
)


PW = "test-" + "pw-12345"
TOK = "tick-" + "tok123"


def make_user(username="frank"):
    u = User.objects.create_user(username, email=f"{username}@example.com")
    u.set_password(PW)
    u.save()
    return u


class UnitsTests(TestCase):
    def test_glucose_roundtrip(self):
        mmol = U.glucose_from_display("101", "imperial")
        self.assertAlmostEqual(float(mmol), 5.607, places=2)
        disp, label = U.glucose_display(mmol, "imperial")
        self.assertEqual(label, "mg/dL")
        self.assertEqual(str(disp), "101")

    def test_weight_roundtrip(self):
        kg = U.weight_from_display("154.3", "imperial")
        disp, label = U.weight_display(kg, "imperial")
        self.assertEqual(label, "lb")
        self.assertEqual(str(disp), "154.3")

    def test_metric_display(self):
        disp, label = U.glucose_display(Decimal("5.6"), "metric")
        self.assertEqual((str(disp), label), ("5.6", "mmol/L"))


class ModelTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_uuid_pks(self):
        r = GlucoseReading.objects.create(user=self.user, value_mmol=Decimal("5.5"))
        self.assertEqual(len(str(r.id)), 36)
        for model in (WeightReading, BloodPressureReading, Profile,
                      MetricSettings, Schedule, OverdueNotice):
            self.assertEqual(model._meta.pk.get_internal_type(), "UUIDField",
                             model.__name__)


class QuickAddTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.c = Client()
        self.c.force_login(self.user)

    def test_add_creates_all_three(self):
        resp = self.c.post("/add/", {
            "taken_at": "2026-10-17T08:00",
            "glucose": "5.8", "weight": "82.4",
            "systolic": "124", "diastolic": "80", "pulse": "66",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(GlucoseReading.objects.count(), 1)
        self.assertEqual(WeightReading.objects.count(), 1)
        b = BloodPressureReading.objects.get()
        self.assertEqual((b.systolic, b.diastolic, b.pulse), (124, 80, 66))

    def test_imperial_input_stored_metric(self):
        Profile.objects.create(user=self.user, units="imperial")
        self.c.post("/add/", {"taken_at": "2026-10-17T08:00",
                              "glucose": "180", "weight": "180"})
        g = GlucoseReading.objects.get()
        self.assertAlmostEqual(float(g.value_mmol), 9.99, places=1)
        w = WeightReading.objects.get()
        self.assertAlmostEqual(float(w.value_kg), 81.65, places=1)

    def test_bp_needs_both(self):
        resp = self.c.post("/add/", {"taken_at": "2026-10-17T08:00", "systolic": "120"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(BloodPressureReading.objects.count(), 0)

    def test_requires_one_value(self):
        resp = self.c.post("/add/", {"taken_at": "2026-10-17T08:00"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(GlucoseReading.objects.count(), 0)

    def test_login_required(self):
        anon = Client()
        resp = anon.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])


class TwoFactorTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.c = Client()

    def _enroll(self):
        import pyotp
        p, _ = Profile.objects.get_or_create(user=self.user)
        p.totp_seed = pyotp.random_base32()
        p.totp_confirmed = True
        p.save()
        return p

    def test_password_then_code(self):
        p = self._enroll()
        self.c.get("/accounts/login/")  # establish session like a real browser
        resp = self.c.post("/accounts/login/", {
            "username": "frank", "password": PW, "next": "/",
        })
        self.assertEqual(resp.status_code, 200)  # code step, not logged in
        self.assertFalse(resp.wsgi_request.user.is_authenticated)
        sess = self.c.session
        self.assertIn("halsa_2fa_user_pk", sess)
        import pyotp
        code = pyotp.TOTP(p.totp_seed).now()
        resp = self.c.post("/accounts/login/", {"code": code})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("_auth_user_id", self.c.session)

    def test_wrong_code_rejected(self):
        self._enroll()
        self.c.post("/accounts/login/", {"username": "frank", "password": PW})
        import pyotp
        from .models import Profile as P
        seed = P.objects.get(user=self.user).totp_seed
        now = pyotp.TOTP(seed).now()
        bad = "000000" if now != "000000" else "000001"
        resp = self.c.post("/accounts/login/", {"code": bad})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.c.session)

    def test_no_2fa_logs_in_directly(self):
        resp = self.c.post("/accounts/login/", {"username": "frank", "password": PW})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("_auth_user_id", self.c.session)


def _schedule(user, metric, at, weekdays=None):
    return Schedule.objects.create(
        user=user, name=f"{metric} slot", metric=metric, time=at,
        weekdays=weekdays if weekdays is not None
        else [timezone.localdate().weekday()],
    )


class SchedulingTests(TestCase):
    def setUp(self):
        self.user = make_user()
        # freeze "now" to 12:00 local
        self.now = timezone.localtime().replace(hour=12, minute=0,
                                               second=0, microsecond=0)

    def test_satisfied_within_window(self):
        s = _schedule(self.user, Metric.GLUCOSE, time(7, 30))
        ms = scheduling.settings_for(self.user, Metric.GLUCOSE)
        slot = s.slot_on(self.now.date())
        GlucoseReading.objects.create(
            user=self.user, taken_at=slot - timedelta(minutes=90),
            value_mmol=Decimal("5.2"))
        self.assertTrue(scheduling.is_satisfied(s, slot, ms))

    def test_not_satisfied_outside_window(self):
        s = _schedule(self.user, Metric.GLUCOSE, time(7, 30))
        ms = scheduling.settings_for(self.user, Metric.GLUCOSE)
        slot = s.slot_on(self.now.date())
        GlucoseReading.objects.create(
            user=self.user, taken_at=slot - timedelta(hours=23),
            value_mmol=Decimal("5.2"))
        self.assertFalse(scheduling.is_satisfied(s, slot, ms))

    def test_overdue_notices_once_and_digest(self):
        from django.core import mail

        s1 = _schedule(self.user, Metric.GLUCOSE, time(7, 30))
        s2 = _schedule(self.user, Metric.BP, time(7, 45))
        # both slots 5h ago, nothing logged
        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            result = scheduling.run_tick(self.now)
            self.assertEqual(result["emails_sent"], 1)  # ONE digest
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("2 measurements overdue", mail.outbox[0].subject)
            self.assertIn("/add/", mail.outbox[0].body)  # link included
            self.assertEqual(OverdueNotice.objects.count(), 2)
            # second tick: no re-notify
            scheduling.run_tick(self.now + timedelta(minutes=5))
            self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(s1.notices.exists() and s2.notices.exists())

    def test_grace_respected(self):
        from django.core import mail
        _schedule(self.user, Metric.WEIGHT, time(11, 30))  # 30 min ago
        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            scheduling.run_tick(self.now)  # grace 60 -> not yet
            self.assertEqual(len(mail.outbox), 0)
            scheduling.run_tick(self.now + timedelta(minutes=45))  # 75 min -> yes
            self.assertEqual(len(mail.outbox), 1)

    def test_per_metric_window_config(self):
        s = _schedule(self.user, Metric.GLUCOSE, time(7, 30))
        ms = scheduling.settings_for(self.user, Metric.GLUCOSE)
        ms.window_minutes = 15
        ms.save()
        slot = s.slot_on(self.now.date())
        GlucoseReading.objects.create(
            user=self.user, taken_at=slot - timedelta(minutes=90),
            value_mmol=Decimal("5.2"))
        self.assertFalse(scheduling.is_satisfied(s, slot, ms))

    def test_tick_endpoint_auth(self):
        c = Client()
        with self.settings(SCHEDULER_TOKEN=TOK):
            self.assertEqual(c.get("/scheduler/tick/").status_code, 403)
            self.assertEqual(
                c.get("/scheduler/tick/", headers={"authorization": "Bearer " + TOK}).status_code,
                200)


class ExportRestoreTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.c = Client()
        self.c.force_login(self.user)
        GlucoseReading.objects.create(user=self.user, value_mmol=Decimal("5.5"))
        WeightReading.objects.create(user=self.user, taken_at=timezone.now(),
                                     value_kg=Decimal("80.1"))
        BloodPressureReading.objects.create(user=self.user, systolic=120,
                                            diastolic=80)
        _schedule(self.user, Metric.GLUCOSE, time(7, 30))

    def test_json_backup_shape(self):
        resp = self.c.get("/export/json/")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data["app"], "halsa")
        self.assertEqual(len(data["glucose_readings"]), 1)
        self.assertEqual(len(data["blood_pressure_readings"]), 1)
        self.assertEqual(len(data["schedules"]), 1)
        self.assertIn("attachment", resp["Content-Disposition"])

    def test_restore_roundtrip_idempotent(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        raw = self.c.get("/export/json/").content
        # wipe and restore
        GlucoseReading.objects.all().delete()
        resp = self.c.post("/settings/restore/", {
            "backup": SimpleUploadedFile("b.json", raw,
                                         content_type="application/json")})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(GlucoseReading.objects.count(), 1)
        # re-import same file: no duplicates
        self.c.post("/settings/restore/", {
            "backup": SimpleUploadedFile("b.json", raw,
                                         content_type="application/json")})
        self.assertEqual(GlucoseReading.objects.count(), 1)

    def test_restore_rejects_garbage(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.c.post("/settings/restore/", {
            "backup": SimpleUploadedFile("x.json", b'{"app": "nope"}',
                                         content_type="application/json")})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(GlucoseReading.objects.count(), 1)  # untouched

    def test_pdf_report(self):
        resp = self.c.get("/export/pdf/?range=90")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertGreater(len(resp.content), 1500)


class PageTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.c = Client()
        self.c.force_login(self.user)
        now = timezone.now()
        for i in range(10):
            GlucoseReading.objects.create(
                user=self.user, taken_at=now - timedelta(days=i),
                value_mmol=Decimal(5) + Decimal(i) / 10)
            WeightReading.objects.create(
                user=self.user, taken_at=now - timedelta(days=i),
                value_kg=Decimal("82") - Decimal(i) / 10)
            BloodPressureReading.objects.create(
                user=self.user, taken_at=now - timedelta(days=i),
                systolic=120 + i, diastolic=78)

    def test_pages_render(self):
        for url in ["/", "/add/", "/glucose/", "/weight/", "/pressure/",
                    "/history/", "/schedules/", "/settings/",
                    "/glucose/?range=90", "/pressure/?range=all"]:
            resp = self.c.get(url)
            self.assertEqual(resp.status_code, 200, url)

    def test_dashboard_has_svg_and_insights(self):
        body = self.c.get("/").content.decode()
        self.assertIn("<svg", body)
        self.assertIn("Estimated HbA1c", body)

    def test_edit_and_delete(self):
        g = GlucoseReading.objects.first()
        resp = self.c.post(f"/glucose/edit/{g.id}/", {
            "taken_at": g.taken_at.strftime("%Y-%m-%dT%H:%M"),
            "value": "6.1", "note": "after sport"})
        self.assertEqual(resp.status_code, 302)
        g.refresh_from_db()
        self.assertEqual(str(g.value_mmol), "6.10")
        resp = self.c.post(f"/glucose/delete/{g.id}/")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(GlucoseReading.objects.filter(id=g.id).exists())

    def test_schedule_crud(self):
        resp = self.c.post("/schedules/new/", {
            "name": "Morning glucose", "metric": "glucose", "time": "07:30",
            "weekdays": ["0", "1", "2", "3", "4"], "active": "on"})
        self.assertEqual(resp.status_code, 302)
        s = Schedule.objects.get()
        self.assertEqual(s.weekdays, [0, 1, 2, 3, 4])
        resp = self.c.post(f"/schedules/{s.id}/delete/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Schedule.objects.count(), 0)
