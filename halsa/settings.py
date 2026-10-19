import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=""):
    return os.environ.get(name, default)


def env_list(name, default):
    return [h.strip() for h in env(name, default).split(",") if h.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-key")
DEBUG = env("DEBUG", "0") == "1"
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tracker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "halsa.security.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "halsa.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "halsa.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "halsa"),
        "USER": env("POSTGRES_USER", "halsa"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST", "db"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "Europe/Berlin")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# INSECURE_COOKIES=1 is for the load-test container over plain http only.
_insecure = env("INSECURE_COOKIES", "0") == "1"
SESSION_COOKIE_SECURE = not DEBUG and not _insecure
CSRF_COOKIE_SECURE = not DEBUG and not _insecure
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

# TLS terminates at the operator's reverse proxy. When it forwards
# X-Forwarded-Proto, set HALSA_BEHIND_PROXY=1 so Django recognises https
# requests (correct Secure-cookie handling, HSTS on real TLS answers).
if env("HALSA_BEHIND_PROXY", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HSTS is emitted on TLS answers only (Django guards on is_secure).
# Set HALSA_HSTS_SECONDS=0 to disable while testing a fresh hostname.
_hsts = int(env("HALSA_HSTS_SECONDS", "31536000") or 0)
if _hsts:
    SECURE_HSTS_SECONDS = _hsts
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"


# --- email ------------------------------------------------------------------

_email_map = {
    "HOST": "EMAIL_HOST",
    "PORT": "EMAIL_PORT",
    "USER": "EMAIL_HOST_USER",
    "PASSWORD": "EMAIL_HOST_PASSWORD",
    "TLS": "EMAIL_USE_TLS",
}
for _short, _var in _email_map.items():
    globals()["EMAIL_" + _short] = env(_var)
EMAIL_PORT = int(globals().get("EMAIL_PORT") or 587)
EMAIL_USE_TLS = (globals().get("EMAIL_USE_TLS") or "1") == "1"
globals()["DEFAULT_FROM_EMAIL"] = env("EMAIL_FROM", "halsa@localhost")

if globals().get("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# --- scheduler endpoint -------------------------------------------------------

globals()["SCHEDULER_TOKEN"] = env("SCHEDULER_TOKEN")
globals()["SITE_BASE_URL"] = env("SITE_BASE_URL", "http://localhost")


# --- logging ---------------------------------------------------------------
# Events + errors go to stdout AND /logs/app.log; gunicorn writes the
# access log to stdout AND /logs/access.log (see gunicorn.conf.py).
# Rotation: size-based, multi-process safe (halsa.logsetup).
# Privacy rule: never log measurement values or personal data - events
# and counts only.

LOG_DIR = env("LOG_DIR", "/logs")
LOG_MAX_BYTES = int(env("LOG_MAX_BYTES", "5000000"))
LOG_BACKUP_COUNT = int(env("LOG_BACKUP_COUNT", "5"))
LOG_LEVEL = env("LOG_LEVEL", "INFO")

_logging_handlers = {
    "console": {
        "class": "logging.StreamHandler",
        "stream": "ext://sys.stdout",
        "formatter": "standard",
    },
}
if os.path.isdir(LOG_DIR):
    _logging_handlers["app_file"] = {
        "class": "halsa.logsetup.SafeRotatingFileHandler",
        "filename": os.path.join(LOG_DIR, "app.log"),
        "maxBytes": LOG_MAX_BYTES,
        "backupCount": LOG_BACKUP_COUNT,
        "formatter": "standard",
        "encoding": "utf-8",
    }

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        },
    },
    "handlers": _logging_handlers,
    "root": {"level": LOG_LEVEL, "handlers": list(_logging_handlers)},
    "loggers": {
        # 404s and db chatter are noise; real request errors are ERROR.
        "django.request": {"level": "ERROR", "propagate": True},
        "django.security": {"level": "WARNING", "propagate": True},
        "django.db.backends": {"level": "WARNING", "propagate": True},
        "django.server": {"level": "WARNING", "propagate": True},
        "PIL": {"level": "WARNING", "propagate": True},
    },
}
del _logging_handlers
