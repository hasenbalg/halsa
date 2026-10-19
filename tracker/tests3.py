"""Third wave: file logging, rotation, access config, privacy rule."""

import importlib.util
import logging
import os
import tempfile
from decimal import Decimal

from django.conf import settings
from django.test import Client, TestCase
from django.utils import timezone

from halsa.logsetup import SafeRotatingFileHandler
from .models import GlucoseReading
from .tests import PW, make_user


class SafeRotatingHandlerTests(TestCase):
    def test_rollover_creates_backups(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "app.log")
            h = SafeRotatingFileHandler(path, maxBytes=200, backupCount=2)
            h.setFormatter(logging.Formatter("%(message)s"))
            rec = logging.LogRecord("x", logging.INFO, __file__, 1,
                                    "line-" + "x" * 50, None, None)
            for _ in range(20):
                h.emit(rec)
            h.close()
            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.exists(path + ".1"))
            self.assertTrue(os.path.exists(path + ".2"))
            self.assertFalse(os.path.exists(path + ".3"))

    def test_reopens_after_external_rotation(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "app.log")
            h = SafeRotatingFileHandler(path)
            h.setFormatter(logging.Formatter("%(message)s"))
            rec = logging.LogRecord("x", logging.INFO, __file__, 1,
                                    "before", None, None)
            h.emit(rec)
            # simulate another process rotating the file underneath us
            os.rename(path, path + ".1")
            open(path, "w").close()
            rec2 = logging.LogRecord("x", logging.INFO, __file__, 1,
                                     "after", None, None)
            h.emit(rec2)
            h.close()
            old = open(path + ".1").read()
            new = open(path).read()
            self.assertIn("before", old)
            self.assertNotIn("before", new)
            self.assertIn("after", new)  # landed in the NEW file


class ConfigTests(TestCase):
    def test_django_logging_has_console_and_file(self):
        handlers = settings.LOGGING["handlers"]
        self.assertIn("console", handlers)
        self.assertEqual(
            handlers["console"]["stream"], "ext://sys.stdout")
        if os.path.isdir(settings.LOG_DIR):
            self.assertIn("app_file", handlers)
            self.assertEqual(
                handlers["app_file"]["class"],
                "halsa.logsetup.SafeRotatingFileHandler")
            self.assertTrue(
                handlers["app_file"]["filename"].endswith("app.log"))

    def test_gunicorn_conf_loads(self):
        spec = importlib.util.spec_from_file_location(
            "gunicorn_conf", "/app/gunicorn.conf.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cfg = mod.logconfig_dict
        self.assertIn("gunicorn.access", cfg["loggers"])
        self.assertIn("gunicorn.error", cfg["loggers"])
        self.assertEqual(mod.accesslog, "-")  # stdout
        # file handlers are attached by the hook (gunicorn replaces
        # logconfig handlers when accesslog/errorlog are set)
        mod._attach_file_handlers()
        import logging
        acc = logging.getLogger("gunicorn.access")
        err = logging.getLogger("gunicorn.error")
        if os.path.isdir(mod.LOG_DIR):
            self.assertTrue(any(
                getattr(h, "baseFilename", "") ==
                os.path.join(mod.LOG_DIR, "access.log")
                for h in acc.handlers))
            self.assertTrue(any(
                getattr(h, "baseFilename", "") ==
                os.path.join(mod.LOG_DIR, "app.log")
                for h in err.handlers))
        # idempotent
        n = len(acc.handlers)
        mod._attach_file_handlers()
        self.assertEqual(len(acc.handlers), n)


class EventLogTests(TestCase):
    def setUp(self):
        self.user = make_user("lg")
        self.c = Client()

    def test_login_events_logged(self):
        with self.assertLogs("halsa", level="INFO") as cm:
            self.c.post("/accounts/login/", {"username": "lg",
                                             "password": PW + "x"})
            self.assertIn("login failed", "\n".join(cm.output))
        with self.assertLogs("halsa", level="INFO") as cm:
            self.c.post("/accounts/login/", {"username": "lg",
                             "password": PW})
            self.c.login(username="lg", password=PW)
            self.assertIn("login ok", "\n".join(cm.output))

    def test_reading_saved_logged_without_values(self):
        self.c.login(username="lg", password=PW)
        with self.assertLogs("halsa", level="INFO") as cm:
            self.c.post("/add/", {
                "taken_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "glucose": "5.55", "weight": "", "systolic": "",
                "diastolic": "", "pulse": "", "note": ""})
        out = "\n".join(cm.output)
        self.assertIn("readings saved: glucose", out)
        self.assertNotIn("5.55", out)  # privacy rule

    def test_tick_summary_logged(self):
        tok = "tick-" + "tok123"
        with self.settings(SCHEDULER_TOKEN=tok):
            with self.assertLogs("halsa", level="INFO") as cm:
                resp = self.c.get("/scheduler/tick/",
                                  headers={"authorization": f"Bearer {tok}"})
                self.assertEqual(resp.status_code, 200)
            self.assertIn("tick: checked=", "\n".join(cm.output))
            with self.assertLogs("halsa", level="WARNING") as cm:
                resp = self.c.get("/scheduler/tick/")
                self.assertEqual(resp.status_code, 403)
            self.assertIn("bad token", "\n".join(cm.output))

    def test_restore_and_export_logged(self):
        self.c.login(username="lg", password=PW)
        GlucoseReading.objects.create(user=self.user,
                                      value_mmol=Decimal("5.0"))
        with self.assertLogs("halsa", level="INFO") as cm:
            self.c.get("/export/json/")
        self.assertIn("json export: 1 readings", "\n".join(cm.output))
        with self.assertLogs("halsa", level="INFO") as cm:
            self.c.get("/export/pdf/?range=30")
        self.assertIn("pdf export", "\n".join(cm.output))


class LiveFileTests(TestCase):
    """If /logs exists (container), prove lines actually reach the file."""

    def test_app_log_written(self):
        log_file = os.path.join(settings.LOG_DIR, "app.log")
        if not os.path.isdir(settings.LOG_DIR):
            self.skipTest("no log dir outside the container")
        logging.getLogger("halsa").info("canary-%s", "probe")
        for _ in range(2):
            if "canary-probe" in open(log_file).read():
                return
            logging.getLogger("halsa").handle(
                logging.LogRecord("halsa", logging.INFO, __file__, 1,
                                  "canary-probe", None, None))
        self.fail("canary never reached " + log_file)
