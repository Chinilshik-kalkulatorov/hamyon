"""Test settings: sqlite + locmem cache + eager celery, so the suite runs
anywhere without docker. Redis is replaced by fakeredis in conftest.py."""

from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Rate limiting off in tests (the suite makes many rapid requests per client).
# Scope keys must stay present (value None = no limit) — a view-level
# ScopedRateThrottle raises ImproperlyConfigured if its scope key is missing.
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        "anon": None, "user": None, "login": None, "payment": None, "transfer": None,
    },
}
