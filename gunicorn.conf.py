"""Gunicorn configuration: bind, sizing and logging.

Access log goes to stdout AND /logs/access.log; gunicorn's own errors
go to stdout AND /logs/app.log (same file as Django events). Rotation
is size-based and multi-process safe. Access lines carry request
metadata only - never request bodies, so measurement values can never
appear.

Note: setting accesslog/errorlog makes gunicorn REPLACE the loggers'
handlers with its own stdout handler, so the file handlers defined in
logconfig_dict get dropped. The on_starting/post_fork hooks re-attach
them after gunicorn is done.
"""

import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
# enable access logging + stdout (file handlers re-added by hooks below)
accesslog = "-"
errorlog = "-"
# NOTE: gunicorn 26 always sends "Server: gunicorn" (the old
# server_header switch was removed); strip it at your TLS proxy.
# the line gunicorn pre-formats; no %(f)s/%(a)s (referer/user-agent)
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s'

LOG_DIR = os.environ.get("LOG_DIR", "/logs")
MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", "5000000"))
BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", "5"))

# No %(f)s/%(a)s (referer/user-agent): request metadata only.
FORMAT_DEFAULT = "%(asctime)s %(levelname)s [gunicorn] %(message)s"
FORMAT_ACCESS = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s'

logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": FORMAT_DEFAULT},
        "access": {"format": FORMAT_ACCESS},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "default",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "gunicorn.error": {"level": "INFO", "handlers": ["console"],
                           "propagate": False},
        "gunicorn.access": {"level": "INFO", "handlers": ["console"],
                            "propagate": False},
    },
}


def _attach_file_handlers():
    """Add rotating file handlers to gunicorn's loggers (idempotent)."""
    import logging

    if not os.path.isdir(LOG_DIR):
        return
    from halsa.logsetup import SafeRotatingFileHandler

    # Access records arrive pre-formatted by gunicorn (message is the
    # whole line), so they need the default %(message)s formatter.
    specs = (("gunicorn.access", "access.log", None),
             ("gunicorn.error", "app.log", FORMAT_DEFAULT))
    for name, fname, fmt in specs:
        target = os.path.join(LOG_DIR, fname)
        lg = logging.getLogger(name)
        if any(getattr(h, "baseFilename", None) == target
               for h in lg.handlers):
            continue
        handler = SafeRotatingFileHandler(
            target, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
            encoding="utf-8")
        handler.setFormatter(logging.Formatter(fmt) if fmt
                             else logging.Formatter())
        lg.addHandler(handler)


def on_starting(server):
    _attach_file_handlers()


def post_fork(server, worker):
    _attach_file_handlers()
