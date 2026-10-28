"""
Django settings for the healthcare backend.

Secrets and anything that differs between machines come from environment
variables. On a development machine they are loaded from a `.env` file next
to manage.py (copy `.env.example` to start). Variables that are already set
in the real environment take precedence over the file.
"""

import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_required(name: str) -> str:
    """Return a required variable, or stop at startup with a clear message."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ImproperlyConfigured(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


def env_bool(name: str, default: bool) -> bool:
    """Read a true/false variable. A typo is an error, not a silent False."""
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be true or false, not {value!r}.")


def env_list(name: str, default: str) -> list[str]:
    """Split a comma-separated variable into a list, skipping blank items."""
    value = os.environ.get(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


# Signs sessions and JWTs, so it must never be hard-coded or committed.
SECRET_KEY = env_required("DJANGO_SECRET_KEY")

# Off unless explicitly switched on: a missing variable must never expose
# debug pages or stack traces.
DEBUG = env_bool("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "patients",
    "doctors",
    "mappings",
]

# Our own user model. It must be set before the first `migrate`,
# because every foreign key to "the user" points at whatever this was then.
AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "config.wsgi.application"


# PostgreSQL is the only database, for development and for tests.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_required("DB_NAME"),
        "USER": env_required("DB_USER"),
        "PASSWORD": env_required("DB_PASSWORD"),
        "HOST": os.environ.get("DB_HOST") or "localhost",
        "PORT": os.environ.get("DB_PORT") or "5432",
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        # Our User has no username, first_name or last_name.
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("email", "name")},
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Django REST Framework: every endpoint requires a valid JWT unless a view
# explicitly opts out, and request bodies must be JSON.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

# SimpleJWT: tokens are signed with HS256 using SECRET_KEY.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
}

# With DEBUG off, Django's default logging sends 500 tracebacks only to
# mail_admins, which isn't configured, so they would be lost. These loggers
# print them to the console (the server log) instead; clients still get only
# a generic message.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "loggers": {
        # Unhandled exceptions (500s), with their tracebacks.
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        # Requests Django rejects as suspicious, e.g. a body over the size limit.
        "django.security": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
