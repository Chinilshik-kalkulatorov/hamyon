"""One-time codes. Only the SHA-256 hash (with a settings-side pepper) is kept,
only in Redis, only for 90 seconds. The raw code exists in memory and in the
Telegram message — never in logs, error messages or the database.

Redis keys:
    otp:{user_id}:{purpose}           -> sha256(code + pepper), TTL 90s
    otp:{user_id}:{purpose}:attempts  -> wrong-attempt counter
    otp:{user_id}:{purpose}:lock      -> set after 3 wrong attempts, TTL 600s
"""

import hashlib
import hmac
import secrets

from django.conf import settings

from apps.core.redis import get_redis

from .telegram import send_telegram_otp

PURPOSES = {"payment", "p2p", "withdraw"}


class OTPError(Exception):
    pass


class OTPLockedError(OTPError):
    """Too many wrong attempts: key locked for 10 minutes."""


class OTPInvalidError(OTPError):
    """Submitted code does not match."""


class OTPMissingError(OTPError):
    """No active code (expired, already used, or never sent)."""


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode() + settings.OTP_PEPPER.encode()).hexdigest()


def _keys(user_id, purpose):
    base = f"otp:{user_id}:{purpose}"
    return base, f"{base}:attempts", f"{base}:lock"


def send_otp(user, purpose: str) -> None:
    assert purpose in PURPOSES, f"unknown OTP purpose: {purpose}"
    key, attempts_key, lock_key = _keys(user.pk, purpose)
    r = get_redis()

    if r.exists(lock_key):
        raise OTPLockedError()

    code = f"{secrets.randbelow(1_000_000):06d}"
    pipe = r.pipeline()
    pipe.set(key, _hash(code), ex=settings.OTP_TTL_SECONDS)
    pipe.delete(attempts_key)
    pipe.execute()

    # Demo deployment only (off by default): expose the code to the owner via
    # /api/demo/last-otp/ so the public showcase works without a Telegram bot.
    if getattr(settings, "OTP_DEMO_ECHO", False):
        r.set(f"demo:otp:{user.pk}", code, ex=settings.OTP_TTL_SECONDS)

    # The only place the raw code leaves this process.
    send_telegram_otp(
        user,
        f"Hamyon code: {code}. Valid for {settings.OTP_TTL_SECONDS} seconds. "
        f"Never share this code.",
    )


def verify_otp(user, purpose: str, submitted: str) -> bool:
    """Single-use verify: the key is deleted on first success."""
    key, attempts_key, lock_key = _keys(user.pk, purpose)
    r = get_redis()

    if r.exists(lock_key):
        raise OTPLockedError()

    stored = r.get(key)
    if stored is None:
        raise OTPMissingError()

    if hmac.compare_digest(stored, _hash(submitted)):
        r.delete(key, attempts_key)
        return True

    attempts = r.incr(attempts_key)
    r.expire(attempts_key, settings.OTP_TTL_SECONDS)
    if attempts >= settings.OTP_MAX_ATTEMPTS:
        pipe = r.pipeline()
        pipe.set(lock_key, "1", ex=settings.OTP_LOCK_SECONDS)
        pipe.delete(key, attempts_key)
        pipe.execute()
        raise OTPLockedError()
    raise OTPInvalidError()


def invalidate(user, purpose: str) -> None:
    key, attempts_key, _ = _keys(user.pk, purpose)
    get_redis().delete(key, attempts_key)
