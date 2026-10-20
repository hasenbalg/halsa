"""Tests for glucose meal context (issue #9)."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import GlucoseContext, GlucoseReading, Profile


def _user(name):
    u = get_user_model().objects.create_user(username=name, password="pw-12345-x")
    Profile.objects.filter(user=u).update(units=Profile.Units.METRIC)
    return u


class ContextQuickAddTests(TestCase):
    def setUp(self):
        self.u = _user("ctxadd")
        self.client.force_login(self.u)

    def _post(self, context):
        return self.client.post(reverse("add"), {
            "taken_at": "2026-10-20T08:00",
            "glucose": "5.5",
            "glucose_context": context,
            "weight": "", "systolic": "", "diastolic": "", "pulse": "",
        }, follow=True)

    def test_add_with_context(self):
        r = self._post("fasting")
        self.assertEqual(r.status_code, 200)
        g = GlucoseReading.objects.get(user=self.u)
        self.assertEqual(g.context, "fasting")

    def test_add_without_context_allowed(self):
        self._post("")
        g = GlucoseReading.objects.get(user=self.u)
        self.assertEqual(g.context, "")

    def test_invalid_context_rejected(self):
        before = GlucoseReading.objects.filter(user=self.u).count()
        resp = self._post("banana")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            GlucoseReading.objects.filter(user=self.u).count(), before)

    def test_edit_form_shows_and_saves_context(self):
        g = GlucoseReading.objects.create(
            user=self.u, taken_at=timezone.now(),
            value_mmol=Decimal("6.1"), context="pre")
        resp = self.client.get(reverse("edit", args=["glucose", g.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Before meal")
        resp = self.client.post(reverse("edit", args=["glucose", g.id]), {
            "taken_at": timezone.localtime(g.taken_at).strftime("%Y-%m-%dT%H:%M"),
            "context": "post", "value": "6.1", "note": "",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        g.refresh_from_db()
        self.assertEqual(g.context, "post")

    def test_plain_labels_in_history(self):
        GlucoseReading.objects.create(
            user=self.u, taken_at=timezone.now(),
            value_mmol=Decimal("5.0"), context="post")
        resp = self.client.get(reverse("history"))
        self.assertContains(resp, "After meal")
        self.assertNotContains(resp, "Postprandial")


class ContextChartTests(TestCase):
    def setUp(self):
        self.u = _user("ctxchart")
        self.client.force_login(self.u)

    def test_chart_markers_per_context(self):
        now = timezone.now()
        for i, ctx in enumerate(["fasting", "pre", "post", "random"]):
            GlucoseReading.objects.create(
                user=self.u, taken_at=now - timezone.timedelta(days=i),
                value_mmol=Decimal("5.5"), context=ctx)
        resp = self.client.get(reverse("glucose"))
        svg = resp.content.decode()
        self.assertIn("<polygon", svg)      # random = triangle
        self.assertIn("rotate(45", svg)     # pre = diamond
        self.assertIn('r="3"', svg)         # fasting = big circle


class ContextBackupTests(TestCase):
    def setUp(self):
        self.u = _user("ctxbk")
        self.client.force_login(self.u)

    def _post_backup(self, client, payload):
        import json
        from django.core.files.uploadedfile import SimpleUploadedFile
        return client.post(reverse("restore"),
                           {"backup": SimpleUploadedFile(
                               "backup.json",
                               json.dumps(payload).encode("utf-8"),
                               content_type="application/json")},
                           follow=True)

    def test_export_import_roundtrip(self):
        GlucoseReading.objects.create(
            user=self.u, taken_at=timezone.now(),
            value_mmol=Decimal("5.2"), context="fasting")
        resp = self.client.get(reverse("export_json"))
        import json
        payload = json.loads(resp.content)
        self.assertEqual(payload["glucose_readings"][0]["context"], "fasting")

        GlucoseReading.objects.filter(user=self.u).delete()
        resp = self._post_backup(self.client, payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            GlucoseReading.objects.get(user=self.u).context, "fasting")

    def test_old_backup_without_context_defaults_blank(self):
        payload = {
            "app": "halsa", "export_version": 1,
            "glucose_readings": [{
                "taken_at": "2026-10-01T08:00:00+00:00",
                "value_mmol": "5.4", "note": "legacy",
            }],
        }
        resp = self._post_backup(self.client, payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            GlucoseReading.objects.get(user=self.u).context, "")


class ContextPdfTests(TestCase):
    def test_pdf_uses_latin_terms(self):
        u = _user("ctxpdf")
        GlucoseReading.objects.create(
            user=u, taken_at=timezone.now(),
            value_mmol=Decimal("5.9"), context="post")
        from .pdfexport import build_report
        pdf = build_report(u, Profile.Units.METRIC, 90)
        # reportlab compresses content streams; decompress before matching
        import base64
        import re
        import zlib
        text = b""
        for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf, re.S):
            blob = m.group(1).rstrip(b"\r\n~>")
            try:
                text += zlib.decompress(base64.a85decode(blob, adobe=False))
            except Exception:
                text += blob
        self.assertIn(b"Postprandial", text)

    def test_latin_map_covers_all_choices(self):
        from .models import GLUCOSE_CONTEXT_LATIN
        for value, _label in GlucoseContext.choices:
            self.assertIn(value, GLUCOSE_CONTEXT_LATIN)
