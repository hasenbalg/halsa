from django.test import Client, TestCase


class OpenRedirectAuditTests(TestCase):
    """Audit regression: protocol-relative next must be coerced."""

    def test_protocol_relative_next_rejected(self):
        c = Client()
        r = c.get("/accounts/login/", {"next": "//evil.example/x"})
        self.assertContains(r, 'name="next" value="/"')

    def test_backslash_next_rejected(self):
        c = Client()
        r = c.get("/accounts/login/", {"next": "/\\evil.example"})
        self.assertContains(r, 'name="next" value="/"')

    def test_safe_next_preserved(self):
        c = Client()
        r = c.get("/accounts/login/", {"next": "/glucose/"})
        self.assertContains(r, 'name="next" value="/glucose/"')
