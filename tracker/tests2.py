"""Second wave: charts, trends, restore edge cases, 2FA flow, settings, views."""

import json
from datetime import date, time, timedelta
from decimal import Decimal

from django.core import mail
from django.test import Client, TestCase
from django.utils import timezone

from . import charts, trends, units as U
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
from .restore import RestoreError, restore_from_json
from .scheduling import run_tick, settings_for, status_rows
from .tests import PW, _schedule, make_user

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


class ChartTests(TestCase):
    def test_empty_series(self):
        svg = str(charts.line_chart([{"points": []}]))
        self.assertIn("No data yet", svg)

    def test_single_point_and_band(self):
        now = timezone.now()
        svg = str(charts.line_chart(
            [{"points": [(now, 5.0)], "color": "var(--glucose)"}],
            band=(3.9, 7.8), aria_label="test"))
        self.assertIn("<svg", svg)
        self.assertIn("rect", svg)  # band drawn

    def test_dual_series_and_dashed(self):
        now = timezone.now()
        pts1 = [(now - timedelta(days=i), 120 + i) for i in range(5)]
        pts2 = [(now - timedelta(days=i), 80) for i in range(5)]
        svg = str(charts.line_chart([
            {"points": pts1, "color": "var(--bp)"},
            {"points": pts2, "color": "var(--accent)", "fill": False,
             "dashed": True},
        ], y_decimals=0, show_x=True))
        self.assertIn("polyline", svg)
        self.assertIn("stroke-dasharray", svg)

    def test_sparkline_dates_formats(self):
        now = timezone.now()
        for days in (1, 30, 400):
            pts = [(now - timedelta(days=days - i), 1.0 + i) for i in range(4)]
            svg = str(charts.sparkline(pts))
            self.assertIn("<svg", svg)

    def test_equal_values_expand(self):
        now = timezone.now()
        pts = [(now - timedelta(days=i), 5.0) for i in range(3)]
        svg = str(charts.line_chart([{"points": pts, "color": "x"}]))
        self.assertIn("polyline", svg)


class TrendTests(TestCase):
    def setUp(self):
        self.user = make_user("t")
        self.now = timezone.now()

    def test_weight_down_then_up(self):
        for i in range(10):  # falling last 4 weeks
            WeightReading.objects.create(
                user=self.user, date=(self.now - timedelta(days=i)).date(),
                value_kg=Decimal(80) - Decimal(i) / 5)
        out = trends.weight_insights(
            WeightReading.objects.filter(user=self.user), "metric")
        self.assertTrue(any("trending down" in i["text"] for i in out))
        WeightReading.objects.all().delete()
        for i in range(10):
            WeightReading.objects.create(
                user=self.user, date=(self.now - timedelta(days=i)).date(),
                value_kg=Decimal(80) + Decimal(i) / 5)
        out = trends.weight_insights(
            WeightReading.objects.filter(user=self.user), "metric")
        self.assertTrue(any("trending up" in i["text"] for i in out))

    def test_weight_quarter_comparison(self):
        for i in range(6):
            WeightReading.objects.create(
                user=self.user, date=(self.now - timedelta(days=i)).date(),
                value_kg=Decimal("78"))
            WeightReading.objects.create(
                user=self.user,
                date=(self.now - timedelta(days=100 + i)).date(),
                value_kg=Decimal("82"))
        out = trends.weight_insights(
            WeightReading.objects.filter(user=self.user), "imperial")
        self.assertTrue(any("below the previous quarter" in i["text"] for i in out))

    def test_glucose_above_target_and_prior(self):
        for i in range(5):
            GlucoseReading.objects.create(
                user=self.user, taken_at=self.now - timedelta(days=i),
                value_mmol=Decimal("9.0"))
            GlucoseReading.objects.create(
                user=self.user,
                taken_at=self.now - timedelta(days=15 + i),
                value_mmol=Decimal("7.0"))
        out = trends.glucose_insights(
            GlucoseReading.objects.filter(user=self.user), "metric")
        text = " ".join(i["text"] for i in out)
        self.assertIn("above target", text)
        self.assertIn("up from", text)

    def test_glucose_hba1c_and_range(self):
        for i in range(15):
            GlucoseReading.objects.create(
                user=self.user, taken_at=self.now - timedelta(days=i * 3),
                value_mmol=Decimal("5.5"))
        out = trends.glucose_insights(
            GlucoseReading.objects.filter(user=self.user), "metric")
        text = " ".join(i["text"] for i in out)
        self.assertIn("Estimated HbA1c", text)
        self.assertIn("in range", text)

    def test_bp_elevated_and_slope(self):
        for i in range(6):
            BloodPressureReading.objects.create(
                user=self.user, taken_at=self.now - timedelta(days=i),
                systolic=140 + i, diastolic=90)
            BloodPressureReading.objects.create(
                user=self.user,
                taken_at=self.now - timedelta(days=15 + i),
                systolic=150, diastolic=90)
        out = trends.bp_insights(
            BloodPressureReading.objects.filter(user=self.user), "metric")
        text = " ".join(i["text"] for i in out)
        self.assertIn("elevated", text)
        self.assertIn("down", text)  # vs prior two weeks
        self.assertIn("falling", text)  # 90-day slope


class RestoreEdgeTests(TestCase):
    def setUp(self):
        self.user = make_user("r")

    def _payload(self, **over):
        base = {
            "app": "halsa", "export_version": 1,
            "glucose_readings": [], "weight_readings": [],
            "blood_pressure_readings": [], "schedules": [],
            "metric_settings": [], "profile": {},
        }
        base.update(over)
        return json.dumps(base)

    def test_bad_json(self):
        with self.assertRaises(RestoreError):
            restore_from_json(self.user, "{not json")

    def test_not_a_backup(self):
        with self.assertRaises(RestoreError):
            restore_from_json(self.user, json.dumps({"app": "other"}))

    def test_bad_version(self):
        with self.assertRaises(RestoreError):
            restore_from_json(self.user, self._payload(export_version=99))

    def test_bad_values_rejected_atomically(self):
        payload = self._payload(glucose_readings=[
            {"id": None, "taken_at": "2026-10-01T08:00+02:00",
             "value_mmol": "5.5"},
            {"id": None, "taken_at": "not-a-date", "value_mmol": "5.5"},
        ])
        with self.assertRaises(RestoreError):
            restore_from_json(self.user, payload)
        self.assertEqual(GlucoseReading.objects.count(), 0)  # rolled back

    def test_full_restore_with_all_sections(self):
        payload = self._payload(
            weight_readings=[{"date": "2026-10-01", "value_kg": "80.0"}],
            blood_pressure_readings=[{
                "taken_at": "2026-10-01T08:00+02:00",
                "systolic": 120, "diastolic": 80, "pulse": None}],
            schedules=[{"id": "11111111-1111-1111-1111-111111111111",
                        "name": "S", "metric": "glucose", "time": "07:30",
                        "weekdays": [1, 2], "active": True}],
            metric_settings=[{"metric": "glucose", "window_minutes": 30,
                              "grace_minutes": 15, "email_enabled": False}],
            profile={"units": "imperial"},
        )
        summary = restore_from_json(self.user, payload)
        self.assertEqual(summary["created"]["weight"], 1)
        self.assertEqual(summary["created"]["schedules"], 1)
        self.assertEqual(
            MetricSettings.objects.get(metric="glucose").window_minutes, 30)
        self.assertEqual(Profile.objects.get(user=self.user).units, "imperial")
        # second import updates, not duplicates
        summary = restore_from_json(self.user, payload)
        self.assertEqual(summary["updated"]["schedules"], 1)
        self.assertEqual(Schedule.objects.count(), 1)

    def test_bad_time_and_number(self):
        for bad in (
            self._payload(schedules=[{"name": "x", "metric": "glucose",
                                      "time": "25:99", "weekdays": []}]),
            self._payload(weight_readings=[{"date": "2026-01-01",
                                            "value_kg": "abc"}]),
            self._payload(weight_readings=[{"date": "nope",
                                            "value_kg": "80"}]),
        ):
            with self.assertRaises(RestoreError):
                restore_from_json(self.user, bad)


class TwoFactorFlowTests(TestCase):
    def setUp(self):
        self.user = make_user("tf")
        self.c = Client()
        self.c.login(username="tf", password=PW)
    def test_enroll_confirm_disable(self):
        # enroll
        resp = self.c.post("/settings/2fa/", {"action": "enroll"})
        self.assertEqual(resp.status_code, 302)
        p = Profile.objects.get(user=self.user)
        self.assertTrue(p.totp_seed)
        self.assertFalse(p.two_factor_enabled)
        page = self.c.get("/settings/2fa/")
        body = page.content.decode()
        self.assertIn("data:image/svg+xml", body)  # QR rendered
        self.assertIn(p.totp_seed, body)           # manual key shown
        # confirm with wrong code re-renders enrollment
        resp = self.c.post("/settings/2fa/", {"action": "confirm",
                                              "code": "000001"})
        self.assertEqual(resp.status_code, 200)
        p.refresh_from_db()
        self.assertFalse(p.totp_confirmed)  # still not enabled
        # confirm with right code
        import pyotp
        code = pyotp.TOTP(p.totp_seed).now()
        resp = self.c.post("/settings/2fa/", {"action": "confirm", "code": code})
        self.assertEqual(resp.status_code, 302)
        p.refresh_from_db()
        self.assertTrue(p.two_factor_enabled)
        # disable requires a valid code
        resp = self.c.post("/settings/2fa/", {"action": "disable",
                                              "code": "123456"})
        p.refresh_from_db()
        self.assertTrue(p.two_factor_enabled)
        code = pyotp.TOTP(p.totp_seed).now()
        resp = self.c.post("/settings/2fa/", {"action": "disable", "code": code})
        self.assertEqual(resp.status_code, 302)
        p.refresh_from_db()
        self.assertFalse(p.two_factor_enabled)
        self.assertEqual(p.totp_seed, "")

    def test_stale_pending_returns_to_password(self):
        p, _ = Profile.objects.get_or_create(user=self.user)
        import pyotp
        p.totp_seed = pyotp.random_base32()
        p.totp_confirmed = True
        p.save()
        c2 = Client()
        c2.post("/accounts/login/", {"username": "tf", "password": PW})
        # disable 2FA mid-flow -> pending user is stale
        p.totp_seed = ""
        p.totp_confirmed = False
        p.save()
        resp = c2.post("/accounts/login/", {"code": "123456"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["step"], "password")

    def test_logout(self):
        self.c.post("/accounts/logout/")
        resp = self.c.get("/")
        self.assertEqual(resp.status_code, 302)

    def test_login_next_validation(self):
        anon = Client()
        resp = anon.get("/accounts/login/?next=https://evil.example/x")
        self.assertIn('value="/"', resp.content.decode())
        # logged-in users get bounced off the login page entirely
        resp = self.c.get("/accounts/login/")
        self.assertEqual(resp.status_code, 302)


class SettingsViewTests(TestCase):
    def setUp(self):
        self.user = make_user("sv")
        self.c = Client()
        self.c.login(username="sv", password=PW)
    def test_units_post(self):
        resp = self.c.post("/settings/", {"units": "imperial"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Profile.objects.get(user=self.user).units, "imperial")

    def test_metric_settings_post(self):
        resp = self.c.post("/settings/", {
            "mglucose-window_minutes": "45",
            "mglucose-grace_minutes": "20",
            "mglucose-email_enabled": "on",
            "mweight-window_minutes": "120",
            "mweight-grace_minutes": "60",
            "mbp-window_minutes": "120",
            "mbp-grace_minutes": "60",
        })
        self.assertEqual(resp.status_code, 302)
        ms = MetricSettings.objects.get(user=self.user, metric="glucose")
        self.assertEqual((ms.window_minutes, ms.grace_minutes), (45, 20))

    def test_imperial_dashboard_conversion(self):
        Profile.objects.create(user=self.user, units="imperial")
        GlucoseReading.objects.create(user=self.user,
                                      value_mmol=Decimal("5.55"))
        body = self.c.get("/").content.decode()
        self.assertIn("100", body)  # 5.55 mmol/L ~ 100 mg/dL
        self.assertIn("mg/dL", body)


class SchedulingExtraTests(TestCase):
    def setUp(self):
        self.user = make_user("sx")
        self.now = timezone.localtime().replace(hour=12, minute=0,
                                               second=0, microsecond=0)

    def test_status_rows(self):
        s = _schedule(self.user, Metric.GLUCOSE, time(7, 30))
        ms = settings_for(self.user, Metric.GLUCOSE)
        ms.grace_minutes = 30
        ms.save()
        rows = status_rows(self.user, self.now)
        self.assertEqual(rows[0]["status"], "overdue")
        GlucoseReading.objects.create(user=self.user,
                                      taken_at=self.now - timedelta(hours=4),
                                      value_mmol=Decimal("5.0"))
        rows = status_rows(self.user, self.now)
        self.assertEqual(rows[0]["status"], "done")
        s.time = time(18, 0)
        s.save()
        rows = status_rows(self.user, self.now)
        self.assertEqual(rows[0]["status"], "today")

    def test_email_disabled_for_metric(self):
        _schedule(self.user, Metric.GLUCOSE, time(7, 30))
        ms = settings_for(self.user, Metric.GLUCOSE)
        ms.email_enabled = False
        ms.save()
        with self.settings(EMAIL_BACKEND=LOCMEM):
            run_tick(self.now)
            self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(OverdueNotice.objects.count(), 1)  # still recorded

    def test_user_without_email(self):
        self.user.email = ""
        self.user.save()
        _schedule(self.user, Metric.GLUCOSE, time(7, 30))
        with self.settings(EMAIL_BACKEND=LOCMEM):
            result = run_tick(self.now)
            self.assertEqual(result["emails_sent"], 0)

    def test_single_item_email_wording(self):
        _schedule(self.user, Metric.WEIGHT, time(7, 30))
        with self.settings(EMAIL_BACKEND=LOCMEM):
            run_tick(self.now)
            self.assertIn("1 measurement overdue", mail.outbox[0].subject)
            self.assertIn("was due", mail.outbox[0].body)

    def test_next_slot_and_inactive(self):
        s = _schedule(self.user, Metric.WEIGHT, time(9, 0), weekdays=[6])
        nxt = s.next_slot(self.now)
        self.assertEqual(nxt.weekday(), 6)
        self.assertGreater(nxt, self.now)
        s.active = False
        s.save()
        self.assertIsNone(s.next_slot(self.now))

    def test_tick_no_token_configured(self):
        c = Client()
        with self.settings(SCHEDULER_TOKEN=""):
            self.assertEqual(c.get("/scheduler/tick/").status_code, 403)


class ExportExtraTests(TestCase):
    def setUp(self):
        self.user = make_user("ex")
        self.c = Client()
        self.c.login(username="ex", password=PW)
    def test_pdf_empty_data(self):
        resp = self.c.get("/export/pdf/?range=30")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"%PDF", resp.content[:10])
        body = self.c.get("/").content.decode()
        self.assertIn("No data yet", body)

    def test_pdf_all_metrics(self):
        now = timezone.now()
        for i in range(12):
            GlucoseReading.objects.create(
                user=self.user, taken_at=now - timedelta(days=i),
                value_mmol=Decimal("6.0"))
            WeightReading.objects.create(
                user=self.user, date=(now - timedelta(days=i)).date(),
                value_kg=Decimal("80"))
            BloodPressureReading.objects.create(
                user=self.user, taken_at=now - timedelta(days=i),
                systolic=120, diastolic=80, pulse=60)
        resp = self.c.get("/export/pdf/?range=all")
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.content), 3000)

    def test_json_empty_backup(self):
        data = json.loads(self.c.get("/export/json/").content)
        self.assertEqual(data["glucose_readings"], [])
        self.assertEqual(data["profile"]["username"], "ex")

    def test_restore_too_large_and_missing(self):
        resp = self.c.post("/settings/restore/", {})
        self.assertEqual(resp.status_code, 302)  # error message, no crash


class EditFlowTests(TestCase):
    def setUp(self):
        self.user = make_user("ef")
        self.c = Client()
        self.c.login(username="ef", password=PW)
    def test_weight_edit_imperial(self):
        Profile.objects.create(user=self.user, units="imperial")
        w = WeightReading.objects.create(user=self.user, date=date.today(),
                                         value_kg=Decimal("80.0"))
        page = self.c.get(f"/weight/edit/{w.id}/")
        self.assertIn(b"176", page.content)  # 80 kg shown as ~176 lb
        resp = self.c.post(f"/weight/edit/{w.id}/",
                           {"date": "2026-10-17", "value": "176.37",
                            "note": ""})
        self.assertEqual(resp.status_code, 302)
        w.refresh_from_db()
        self.assertAlmostEqual(float(w.value_kg), 80.0, places=1)

    def test_bp_edit_rejects_inverted(self):
        b = BloodPressureReading.objects.create(user=self.user, systolic=120,
                                                diastolic=80)
        resp = self.c.post(f"/bp/edit/{b.id}/", {
            "taken_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "systolic": "70", "diastolic": "110", "pulse": "", "note": ""})
        self.assertEqual(resp.status_code, 200)
        b.refresh_from_db()
        self.assertEqual(b.systolic, 120)

    def test_edit_other_users_object_404(self):
        other = make_user("other")
        g = GlucoseReading.objects.create(user=other,
                                          value_mmol=Decimal("5.0"))
        resp = self.c.get(f"/glucose/edit/{g.id}/")
        self.assertEqual(resp.status_code, 404)


class UnitsEdgeTests(TestCase):
    def test_fmt_helpers(self):
        self.assertEqual(U.fmt_bp(120, 80), "120/80")
        self.assertEqual(U.glucose_unit_label("imperial"), "mg/dL")
        self.assertEqual(U.weight_unit_label("metric"), "kg")
        self.assertEqual(str(U.glucose_display(Decimal("3.9"), "metric")[0]),
                         "3.9")
