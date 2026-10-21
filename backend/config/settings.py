"""Django settings for the attendance service.

All values come from the same ATTENDANCE_* environment variables as the rest of
the service. Two connections to the same database are configured:

- ``default``: read-write, used by the sync, report, and migrate commands;
- ``readonly``: pooled and read-only (``default_transaction_read_only``), used
  by the REST API so it cannot modify attendance data.
"""

from __future__ import annotations

import os
import secrets
from urllib.parse import parse_qsl, unquote, urlsplit

from attendance.services.config import (
    ConfigurationError,
    DatabaseConfig,
    database_pool_sizes,
)


def _database_settings(url: str) -> dict[str, object]:
    parts = urlsplit(url)
    if parts.scheme not in {"postgresql", "postgres"}:
        raise ConfigurationError("ATTENDANCE_DATABASE_URL must be a postgresql:// URL")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parts.path.lstrip("/")),
        "USER": unquote(parts.username or ""),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": parts.hostname or "",
        "PORT": str(parts.port or ""),
        "OPTIONS": dict(parse_qsl(parts.query)),
    }


_DATABASE = _database_settings(DatabaseConfig.from_environment().url)
_POOL_MIN_SIZE, _POOL_MAX_SIZE = database_pool_sizes()

# No sessions, cookies, or forms are used, so a per-process key is sufficient.
SECRET_KEY = os.getenv("ATTENDANCE_DJANGO_SECRET_KEY") or secrets.token_urlsafe(50)
DEBUG = False
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ATTENDANCE_API_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = ["attendance"]
MIDDLEWARE = [
    "attendance.middleware.RequestLoggingMiddleware",
    "django.middleware.security.SecurityMiddleware",
]
ROOT_URLCONF = "config.urls"
# Required by Django Ninja to render the /docs page.
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": False}]

DATABASES = {
    "default": _DATABASE,
    "readonly": {
        **_DATABASE,
        "OPTIONS": {
            **_DATABASE["OPTIONS"],
            "options": "-c default_transaction_read_only=on",
            "pool": {
                "min_size": _POOL_MIN_SIZE,
                "max_size": _POOL_MAX_SIZE,
                "name": "attendance-read-api",
            },
        },
    },
}
DATABASE_ROUTERS = ["attendance.routers.MigrateDefaultOnlyRouter"]

USE_TZ = True
TIME_ZONE = "UTC"
USE_I18N = False

# attendance.services.logging_config owns logging configuration.
LOGGING_CONFIG = None
