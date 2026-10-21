"""Tests for issue #10: i18n (browser auto-detect + per-user pin)."""
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone, translation

from tracker.models import Profile


class I18nTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u", password="***")
        self.profile, _ = Profile.objects.get_or_create(user=self.user)

    def _get(self, url, accept):
        return self.client.get(url, headers={"accept-language": accept})

    def test_anonymous_browser_de(self):
        res = self._get("/accounts/login/", "de,en;q=0.8")
        self.assertContains(res, "Anmelden")

    def test_anonymous_browser_en(self):
        res = self._get("/accounts/login/", "en-us")
        self.assertContains(res, "Sign in")

    def test_anonymous_browser_de_chrome_ordering(self):
        res = self._get("/accounts/login/", "en;q=0.9,de;q=0.95")
        self.assertContains(res, "Anmelden")

    def test_auto_profile_follows_browser(self):
        self.client.login(username="u", password="***")
        res = self._get("/", "de")
        self.assertContains(res, "Übersicht")
        res = self._get("/", "en")
        self.assertContains(res, "Dashboard")

    def test_pinned_de_beats_en_browser(self):
        self.profile.language = "de"
        self.profile.save()
        self.client.login(username="u", password="***")
        res = self._get("/", "en")
        self.assertContains(res, "Übersicht")

    def test_pinned_en_beats_de_browser(self):
        self.profile.language = "en"
        self.profile.save()
        self.client.login(username="u", password="***")
        res = self._get("/", "de")
        self.assertContains(res, "Dashboard")

    def test_settings_language_change_persists(self):
        self.client.login(username="u", password="***")
        res = self.client.post("/settings/", {"language": "de"},
                               follow=True)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.language, "de")
        self.assertContains(res, "Sprache aktualisiert")
        # pinned now: German even with en browser
        res = self._get("/", "en")
        self.assertContains(res, "Übersicht")

    def test_settings_page_shows_language_form(self):
        self.client.login(username="u", password="***")
        res = self._get("/settings/", "de")
        self.assertContains(res, "Sprache")
        self.assertContains(res, 'value="de"')

    def test_login_sets_language_cookie(self):
        self.profile.language = "de"
        self.profile.save()
        res = self.client.post("/accounts/login/",
                               {"username": "u", "password": "***"})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.cookies["django_language"].value, "de")
        # anonymous login page now German even with en browser
        self.client.post("/accounts/logout/")
        self.client.cookies["django_language"] = "de"
        res = self._get("/accounts/login/", "en")
        self.assertContains(res, "Anmelden")

    def test_email_uses_pinned_language(self):
        import datetime
        from django.core import mail
        from django.test import override_settings
        from tracker.models import Schedule
        from tracker.scheduling import run_tick, settings_for
        self.user.email = "u@example.com"
        self.user.save()
        self.profile.language = "de"
        self.profile.save()
        from .tests import _schedule
        _schedule(self.user, "glucose", datetime.time(7, 30))
        ms = settings_for(self.user, "glucose")
        ms.email_enabled = True
        ms.save()
        # pin "now" to midday so the 07:30 slot is always overdue
        now = timezone.localtime().replace(hour=12, minute=0,
                                           second=0, microsecond=0)
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            run_tick(now)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Hallo u,", mail.outbox[0].body)
        self.assertIn("Jetzt erfassen", mail.outbox[0].body)
        self.assertIn("überfällig", mail.outbox[0].subject)

    def test_pdf_uses_pinned_language(self):
        self.profile.language = "de"
        self.profile.save()
        from tracker.pdfexport import build_report
        with translation.override("de"):
            pdf = build_report(self.user, Profile.Units.METRIC, 90)
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
        self.assertIn(b"Gesundheitsbericht", text)

    def test_german_uses_du_not_sie(self):
        self.profile.language = "de"
        self.profile.save()
        self.client.login(username="u", password="***")
        res = self._get("/settings/", "de")
        html = res.content.decode()
        self.assertNotIn("Ihre", html)
        self.assertIn("deine", html.lower())
