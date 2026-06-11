import re

import fakeredis
import pytest
from rest_framework.test import APIClient

from apps.core.models import LedgerEntry, Wallet
from apps.core.services.ledger import post_entry
from apps.users.models import KYCLevel, User


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    """All OTP Redis traffic goes to an in-memory fake."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("apps.core.redis._client", fake)
    return fake


@pytest.fixture
def otp_inbox(monkeypatch):
    """Captures OTP codes instead of 'sending' them to Telegram."""
    codes = []

    def capture(user, text):
        codes.append(re.search(r"\b(\d{6})\b", text).group(1))
        return True

    monkeypatch.setattr("apps.otp.service.send_telegram_otp", capture)
    return codes


@pytest.fixture
def admin(db):
    return User.objects.create_user(
        "admin", password="x", is_staff=True, is_superuser=True
    )


@pytest.fixture
def alice(db):
    return User.objects.create_user(
        "alice", password="x", phone="+998900000001",
        kyc_level=KYCLevel.FULL, telegram_chat_id="111",
    )


@pytest.fixture
def bob(db):
    return User.objects.create_user(
        "bob", password="x", phone="+998900000002",
        kyc_level=KYCLevel.BASIC, telegram_chat_id="222",
    )


@pytest.fixture
def alice_wallet(alice):
    wallet = Wallet.objects.create(user=alice)
    post_entry(wallet, LedgerEntry.Type.CREDIT, 100_000)  # tiyin
    return wallet


@pytest.fixture
def bob_wallet(bob):
    return Wallet.objects.create(user=bob)


@pytest.fixture
def auth_client():
    def make(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    return make
