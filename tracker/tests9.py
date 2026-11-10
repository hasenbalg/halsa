"""Issue #21: blood glucose unit independent of weight unit."""
import json
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from .models import (BloodPressureReading, GlucoseReading, Profile,
                     WeightReading)
from .tests import make_user


class GlucoseUnitTests(TestCase):
    def setUp(self):
        self.user = make_user("unit21")
        self.c = Client()
        self.c.force_login(self.user)
        self.profile = Profile.objects.create(user=self.user)

    def _mixed(self):
        """kg + mg/dL — the combination this issue is about."""
        self.profile.units = "metric"
        self.profile.glucose_units = "imperial"
        self.profile.save()
        GlucoseReading.objects.create(user=self.user,
                                      value_mmol=Decimal("5.55"))
        WeightReading.objects.create(user=self.user,
                                     taken_at=timezone.now(),
                                     value_kg=Decimal("80.0"))

    def test_new_profile_defaults(self):
        self.assertEqual(self.profile.units, "metric")
        self.assertEqual(self.profile.glucose_units, "metric")

    def test_dashboard_mixed_units(self):
        self._mixed()
        body = self.c.get("/").content.decode()
        self.assertIn("mg/dL", body)      # glucose card
        self.assertIn("100", body)        # 5.55 mmol -> ~100 mg/dL
        self.assertIn("80", body)         # weight stays kg
        self.assertIn("kg", body)

    def test_add_form_mixed_labels(self):
        self._mixed()
        body = self.c.get("/add/").content.decode()
        self.assertIn("Glucose (mg/dL)", body)
        self.assertIn("Weight (kg)", body)

    def test_quick_add_stores_canonical(self):
        self.profile.units = "metric"
        self.profile.glucose_units = "imperial"
        self.profile.save()
        self.c.post("/add/", {"taken_at": "2026-10-17T08:00",
                              "glucose": "100", "weight": "80"})
        g = GlucoseReading.objects.get(user=self.user)
        w = WeightReading.objects.get(user=self.user)
        self.assertAlmostEqual(float(g.value_mmol), 5.55, places=1)
        self.assertAlmostEqual(float(w.value_kg), 80.0, places=1)

    def test_chart_uses_display_unit(self):
        self._mixed()
        body = self.c.get("/glucose/").content.decode()
        self.assertIn("milligrammes per decilitre", body)  # aria label
        self.assertIn("(mg/dL)", body)
        # y-axis ticks are mg/dL values; mmol labelling must be gone
        self.assertIn(">100</text>", body)
        self.assertNotIn("mmol per litre", body)
        # metric profile still gets the mmol chart
        self.profile.glucose_units = "metric"
        self.profile.save()
        body = self.c.get("/glucose/").content.decode()
        self.assertIn("mmol per litre", body)
        self.assertIn("(mmol/L)", body)

    def test_units_form_independent_update(self):
        resp = self.c.post("/settings/", {"units": "imperial",
                                          "glucose_units": "metric"})
        self.assertEqual(resp.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.units, "imperial")
        self.assertEqual(self.profile.glucose_units, "metric")

    def test_backup_roundtrip(self):
        self.profile.glucose_units = "imperial"
        self.profile.save()
        payload = json.loads(self.c.get("/export/json/").content)
        self.assertEqual(payload["profile"]["glucose_units"], "imperial")
        self.profile.glucose_units = "metric"
        self.profile.save()
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.c.post("/settings/restore/", {
            "backup": SimpleUploadedFile(
                "b.json", json.dumps(payload).encode(),
                content_type="application/json")})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.glucose_units, "imperial")

    def test_pdf_mixed_units(self):
        self._mixed()
        import base64
        import re
        import zlib
        from .pdfexport import build_report
        raw = build_report(self.user, 90)
        raw = raw if isinstance(raw, bytes) else raw.getvalue()
        joined = b""
        for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
            blob = m.group(1).rstrip(b"\r\n~>")
            try:
                joined += zlib.decompress(base64.a85decode(blob, adobe=False))
            except Exception:
                joined += blob
        self.assertIn(b"mg/dL", joined)
        self.assertIn(b"kg", joined)

    def test_history_mixed_units(self):
        self._mixed()
        body = self.c.get("/history/").content.decode()
        self.assertIn("mg/dL", body)
        self.assertIn("kg", body)
        self.assertNotIn("mmol/L", body)
