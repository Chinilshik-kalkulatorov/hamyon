import hashlib

import pytest
from django.conf import settings

from apps.otp.service import (
    OTPInvalidError,
    OTPLockedError,
    OTPMissingError,
    send_otp,
    verify_otp,
)

pytestmark = pytest.mark.django_db


def wrong(code):
    return "000000" if code != "000000" else "111111"


def test_otp_roundtrip_and_single_use(alice, otp_inbox):
    send_otp(alice, "payment")
    code = otp_inbox[-1]
    assert verify_otp(alice, "payment", code) is True
    with pytest.raises(OTPMissingError):  # single-use: burned on success
        verify_otp(alice, "payment", code)


def test_only_hash_is_stored_with_ttl(alice, otp_inbox, _fake_redis):
    send_otp(alice, "withdraw")
    code = otp_inbox[-1]
    stored = _fake_redis.get(f"otp:{alice.pk}:withdraw")
    expected = hashlib.sha256(code.encode() + settings.OTP_PEPPER.encode()).hexdigest()
    assert stored == expected and stored != code
    assert 0 < _fake_redis.ttl(f"otp:{alice.pk}:withdraw") <= settings.OTP_TTL_SECONDS


def test_three_wrong_attempts_lock_for_10_minutes(alice, otp_inbox, _fake_redis):
    send_otp(alice, "p2p")
    code = otp_inbox[-1]

    for _ in range(2):
        with pytest.raises(OTPInvalidError):
            verify_otp(alice, "p2p", wrong(code))
    with pytest.raises(OTPLockedError):  # 3rd wrong attempt -> lock
        verify_otp(alice, "p2p", wrong(code))

    with pytest.raises(OTPLockedError):  # even the correct code is refused now
        verify_otp(alice, "p2p", code)
    with pytest.raises(OTPLockedError):  # and resending is refused too
        send_otp(alice, "p2p")

    lock_ttl = _fake_redis.ttl(f"otp:{alice.pk}:p2p:lock")
    assert 0 < lock_ttl <= settings.OTP_LOCK_SECONDS


def test_missing_otp(alice):
    with pytest.raises(OTPMissingError):
        verify_otp(alice, "payment", "123456")


def test_purposes_are_isolated(alice, otp_inbox):
    send_otp(alice, "payment")
    payment_code = otp_inbox[-1]
    with pytest.raises(OTPMissingError):  # code for 'payment' is not valid for 'p2p'
        verify_otp(alice, "p2p", payment_code)
