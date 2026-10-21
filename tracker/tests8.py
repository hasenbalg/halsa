"""Tests for weight readings carrying a time (consistency with glucose/bp)."""
import datetime
import json
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from .models import Profile, WeightReading
from .tests import PW, make_user


class WeightTimeTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.c = Client()
        self.c.force_login(self.user)

    def test_quick_add_stores_time(self):
        when = timezone.localtime().replace(hour=7, minute=23, second=0,
                                           microsecond=0)
        res = self.c.post("/add/", {
            "taken_at": when.strftime("%Y-%m-%dT%H:%M"),
            "weight": "81.2",
        }, follow=True)
        self.assertEqual(res.status_code, 200)
        w = WeightReading.objects.get(user=self.user)
        self.assertEqual(timezone.localtime(w.taken_at).hour, 7)
        self.assertEqual(timezone.localtime(w.taken_at).minute, 23)

    def test_history_shows_weight_time(self):
        when = timezone.localtime().replace(hour=7, minute=23, second=0,
                                           microsecond=0)
        WeightReading.objects.create(user=self.user, taken_at=when,
                                     value_kg=Decimal("81.2"))
        res = self.c.get("/history/")
        self.assertContains(res, "today 07:23")

    def test_metric_page_shows_weight_time(self):
        when = timezone.localtime() - datetime.timedelta(days=3)
        when = when.replace(hour=6, minute=45, second=0, microsecond=0)
        WeightReading.objects.create(user=self.user, taken_at=when,
                                     value_kg=Decimal("81.2"))
        res = self.c.get("/weight/")
        self.assertContains(res, "06:45")

    def test_edit_form_shows_time(self):
        when = timezone.localtime().replace(hour=7, minute=23, second=0,
                                           microsecond=0)
        w = WeightReading.objects.create(user=self.user, taken_at=when,
                                         value_kg=Decimal("81.2"))
        res = self.c.get(f"/weight/edit/{w.id}/")
        self.assertContains(res, "datetime-local")
        self.assertContains(res, when.strftime("%Y-%m-%dT%H:%M"))

    def test_backup_roundtrip_keeps_time(self):
        when = timezone.now().replace(second=0, microsecond=0)
        w = WeightReading.objects.create(user=self.user, taken_at=when,
                                         value_kg=Decimal("81.2"))
        payload = json.loads(self.c.get("/export/json/").content)
        self.assertIn("taken_at", payload["weight_readings"][0])
        WeightReading.objects.all().delete()
        res = self.c.post("/settings/restore/",
                          {"backup": _upload(payload)}, follow=True)
        self.assertEqual(res.status_code, 200)
        w.refresh_from_db()
        self.assertEqual(timezone.localtime(w.taken_at).strftime("%H:%M"),
                         timezone.localtime(when).strftime("%H:%M"))

    def test_legacy_date_only_backup_restores_midnight(self):
        payload = {
            "app": "halsa", "export_version": 1,
            "weight_readings": [{
                "id": "11111111-1111-1111-1111-111111111111",
                "date": "2026-10-01", "value_kg": "80.0",
            }],
        }
        res = self.c.post("/settings/restore/",
                          {"backup": _upload(payload)}, follow=True)
        self.assertEqual(res.status_code, 200)
        w = WeightReading.objects.get(user=self.user)
        local = timezone.localtime(w.taken_at)
        self.assertEqual((local.year, local.month, local.day),
                         (2026, 10, 1))
        self.assertEqual((local.hour, local.minute), (0, 0))

    def test_dashboard_card_shows_time(self):
        when = timezone.localtime().replace(hour=7, minute=23, second=0,
                                           microsecond=0)
        WeightReading.objects.create(user=self.user, taken_at=when,
                                     value_kg=Decimal("81.2"))
        res = self.c.get("/")
        self.assertContains(res, "today 07:23")


def _upload(payload):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(
        "backup.json", json.dumps(payload).encode(),
        content_type="application/json")
