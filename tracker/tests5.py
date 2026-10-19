from django.test import TestCase

CSP_PREFIX = "default-src 'self'; script-src 'none'"


class SecurityHeadersTests(TestCase):
    """App-emitted hardening headers (no reverse proxy involved)."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.user = get_user_model().objects.create_user(
            username="hdr-user", password="Hdr-pw-9182!")

    def test_csp_on_app_pages(self):
        self.client.force_login(self.user)
        r = self.client.get("/")
        self.assertTrue(r["Content-Security-Policy"].startswith(CSP_PREFIX))
        self.assertEqual(r["Referrer-Policy"], "same-origin")
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")

    def test_csp_absent_on_admin(self):
        r = self.client.get("/admin/login/")
        self.assertNotIn("Content-Security-Policy", r)

    def test_hsts_only_on_tls_answers(self):
        self.client.force_login(self.user)
        plain = self.client.get("/")           # http request
        self.assertNotIn("Strict-Transport-Security", plain)
        tls = self.client.get("/", secure=True)  # https request
        self.assertIn("Strict-Transport-Security", tls)
