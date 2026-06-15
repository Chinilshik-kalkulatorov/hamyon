import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-secret-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "apps.users",
    "apps.core",
    "apps.kyc",
    "apps.blacklist",
    "apps.otp",
    "apps.payments",
    "apps.p2p",
    "apps.history",
    "apps.notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Blacklist gate: rejects blocked users/wallets before any transaction view runs.
    "apps.blacklist.middleware.BlacklistMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "hamyon"),
        "USER": os.getenv("DB_USER", "hamyon"),
        "PASSWORD": os.getenv("DB_PASSWORD", "hamyon"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5544"),
    }
}

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6380/1")
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "0") == "1"

AUTH_USER_MODEL = "users.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Production: domain origins trusted for unsafe (POST) requests, e.g. admin login.
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o]
# When behind nginx terminating TLS, trust its forwarded scheme.
if os.getenv("USE_X_FORWARDED_PROTO", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------------ Hamyon ---
# All money amounts are integers in tiyin (1 UZS = 100 tiyin). No floats, ever.

# OTP: only the SHA-256 hash of (code + pepper) is stored, and only in Redis.
OTP_PEPPER = os.getenv("OTP_PEPPER", "dev-pepper-change-me")
OTP_TTL_SECONDS = 90
OTP_MAX_ATTEMPTS = 3
OTP_LOCK_SECONDS = 600

# Dynamic QR codes are signed JWTs (HS256), single-use, 15 minutes.
# HS256 wants a key of at least 32 bytes (RFC 7518).
QR_JWT_SECRET = os.getenv("QR_JWT_SECRET", "dev-qr-secret-change-me-0123456789abcdef")
QR_DYNAMIC_TTL_SECONDS = 15 * 60

# Pending payment / transfer requests expire after this long.
PAYMENT_REQUEST_TTL_SECONDS = 15 * 60

# Rolling 30-day spend limits per KYC level, in tiyin. Configurable, not hardcoded.
KYC_SPEND_LIMITS = {
    "unverified": 500_000_00,       # 500,000 UZS
    "basic": 5_000_000_00,          # 5,000,000 UZS
    "full": 50_000_000_00,          # 50,000,000 UZS
}
KYC_LIMIT_WINDOW_DAYS = 30

# Telegram: empty token = console imitation mode. The OTP bot and the push bot
# are independent on purpose (separate tokens, separate modules, no shared code).
TELEGRAM_OTP_BOT_TOKEN = os.getenv("TELEGRAM_OTP_BOT_TOKEN", "")
TELEGRAM_PUSH_BOT_TOKEN = os.getenv("TELEGRAM_PUSH_BOT_TOKEN", "")

# POSTs to these path prefixes pass through the blacklist middleware gate.
BLACKLIST_GUARDED_PATH_PREFIXES = ["/api/payments/", "/api/p2p/"]

# Base URL used to build links to exported CSV files.
EXPORT_BASE_URL = os.getenv("EXPORT_BASE_URL", "http://localhost:8000")

# Demo-only: echo the latest OTP to the user via /api/demo/last-otp/ so the
# public showcase works without a real Telegram bot. Off by default; OTP
# verification (hash compare) is unaffected.
OTP_DEMO_ECHO = os.getenv("OTP_DEMO_ECHO", "0") == "1"
