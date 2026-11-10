"""Issue #22: optional tor onion service + django-axes hardening."""
from django.db.models import Sum
from django.test import Client, TestCase, override_settings

from .models import Profile
from .tests import PW, make_user

ONION = "abcdefghijklmnopqrstuvwxyz234567.onion"
ONION_URL = f"http://{ONION}"


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", ONION],
                   ONION_URL=ONION_URL)
class OnionGuardTests(TestCase):
    def setUp(self):
        self.user = make_user("og")
        self.c = Client()

    def test_admin_blocked_over_onion(self):
        for path in ("/admin/", "/admin/login/", "/admin/auth/user/"):
            resp = self.c.get(path, headers={"host": ONION})
            self.assertEqual(resp.status_code, 404, path)

    def test_admin_ok_from_lan(self):
        self.c.force_login(self.user)
        resp = self.c.get("/admin/", headers={"host": "localhost"})
        self.assertIn(resp.status_code, (200, 301, 302))

    def test_app_reachable_over_onion(self):
        # the login page itself must work over the onion service
        resp = self.c.get("/accounts/login/", headers={"host": ONION})
        self.assertEqual(resp.status_code, 200)


@override_settings(ONION_URL=ONION_URL)
class OnionPanelTests(TestCase):
    def setUp(self):
        self.user = make_user("op")
        self.c = Client()
        self.c.force_login(self.user)

    def test_panel_with_qr_and_risk_text(self):
        body = self.c.get("/settings/").content.decode()
        self.assertIn("Tor onion service", body)
        self.assertIn(ONION_URL, body)
        self.assertIn('type="text" readonly', body)
        self.assertIn("data:image/svg+xml", body)  # segno QR
        self.assertIn("Before you share this address", body)
        self.assertIn("not reachable over Tor", body)

    @override_settings(ONION_URL="")
    def test_panel_hidden_without_onion(self):
        body = self.c.get("/settings/").content.decode()
        self.assertNotIn("Tor onion service", body)


AXES_DB = "axes.handlers.database.AxesDatabaseHandler"
AXES_DUMMY = "axes.handlers.dummy.AxesDummyHandler"


@override_settings(AXES_HANDLER=AXES_DB, AXES_FAILURE_LIMIT=3,
                   AXES_LOCKOUT_PARAMETERS=[["username", "ip_address"]])
class AxesLockoutTests(TestCase):
    def setUp(self):
        self.user = make_user("ax")
        self.c = Client()

    def _post_login(self, password):
        return self.c.post("/accounts/login/",
                           {"username": "ax", "password": password})

    def test_lockout_after_limit(self):
        for _ in range(3):
            self._post_login(PW + "wrong")
        # right password now: locked client is refused, session stays anon
        resp = self._post_login(PW)
        self.assertIn(resp.status_code, (403, 429))  # axes lockout
        self.assertNotIn("_auth_user_id", self.c.session)

    def test_success_resets_counter(self):
        self._post_login(PW + "wrong")
        self._post_login(PW + "wrong")
        resp = self._post_login(PW)
        self.assertEqual(resp.status_code, 302)  # login ok
        from axes.models import AccessAttempt
        total = AccessAttempt.objects.filter(username="ax").aggregate(
            t=Sum("failures_since_start"))["t"]
        self.assertTrue(total is None or total == 0)


    def test_shared_onion_ip_does_not_lock_other_users(self):
        # Over the onion every client shares the tor container's address.
        # Burning the limit on one username must not lock a different
        # user's login from the very same IP.
        make_user("vic")
        for _ in range(5):
            self._post_login(PW + "wrong")
        resp = self.c.post("/accounts/login/",
                           {"username": "vic", "password": PW})
        self.assertEqual(resp.status_code, 302)  # victim can still log in
        self.assertIn("_auth_user_id", self.c.session)


@override_settings(AXES_HANDLER=AXES_DB, AXES_FAILURE_LIMIT=10,
                   AXES_LOCKOUT_PARAMETERS=["ip_address"])
class TotpFailureCountedTests(TestCase):
    def test_bad_codes_record_attempts(self):
        import pyotp
        from axes.models import AccessAttempt

        user = make_user("tc")
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.totp_seed = pyotp.random_base32()
        profile.totp_confirmed = True
        profile.save()
        c = Client()
        # one pending ticket per code attempt: password step, then bad code
        for _ in range(2):
            c.post("/accounts/login/", {"username": "tc", "password": PW})
            c.post("/accounts/login/", {"code": "000000"})
        total = sum(a.failures_since_start
                    for a in AccessAttempt.objects.filter(username="tc"))
        self.assertGreaterEqual(total, 2)
