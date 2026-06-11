import time
import uuid

import jwt as pyjwt
import pytest
from django.conf import settings as django_settings

from apps.blacklist.service import block
from apps.core.exceptions import BlockedError, InsufficientFundsError
from apps.core.models import LedgerEntry, Transfer
from apps.core.services.balance import get_wallet_balance
from apps.p2p.models import TransferRequest
from apps.p2p.qr import (
    QRAlreadyUsedError,
    QRInvalidError,
    decode_dynamic_qr,
    issue_dynamic_qr,
)
from apps.p2p.services import confirm_transfer, initiate_transfer

pytestmark = pytest.mark.django_db


def balance(wallet):
    return get_wallet_balance(wallet.id, use_cache=False)


def test_transfer_writes_two_entries_atomically(alice, alice_wallet, bob, bob_wallet,
                                                otp_inbox):
    request, created = initiate_transfer(
        alice, alice_wallet.id, bob_wallet.id, 25_000, uuid.uuid4()
    )
    assert created and request.status == TransferRequest.Status.OTP_PENDING
    # Nothing moves until the sender confirms with OTP.
    assert balance(alice_wallet)["balance"] == 100_000
    assert balance(bob_wallet)["balance"] == 0

    confirm_transfer(alice, request.id, otp_inbox[-1])

    assert balance(alice_wallet)["balance"] == 75_000
    assert balance(bob_wallet)["balance"] == 25_000

    transfer = Transfer.objects.get(idempotency_key=request.idempotency_key)
    assert transfer.debit_entry.wallet_id == alice_wallet.id
    assert transfer.debit_entry.type == LedgerEntry.Type.DEBIT
    assert transfer.credit_entry.wallet_id == bob_wallet.id
    assert transfer.credit_entry.type == LedgerEntry.Type.CREDIT


def test_transfer_initiate_is_idempotent(alice, alice_wallet, bob_wallet, otp_inbox):
    key = uuid.uuid4()
    first, created_first = initiate_transfer(alice, alice_wallet.id, bob_wallet.id,
                                             10_000, key)
    second, created_second = initiate_transfer(alice, alice_wallet.id, bob_wallet.id,
                                               10_000, key)
    assert created_first and not created_second
    assert first.id == second.id
    assert TransferRequest.objects.filter(idempotency_key=key).count() == 1


def test_insufficient_funds_blocks_initiate(alice, alice_wallet, bob_wallet):
    with pytest.raises(InsufficientFundsError):
        initiate_transfer(alice, alice_wallet.id, bob_wallet.id, 999_999, uuid.uuid4())


def test_blocked_recipient_blocks_transfer(admin, alice, alice_wallet, bob, bob_wallet):
    block("user_id", str(bob.pk), "fraud suspicion", by=admin)
    with pytest.raises(BlockedError):
        initiate_transfer(alice, alice_wallet.id, bob_wallet.id, 1_000, uuid.uuid4())


def test_blocked_sender_wallet_blocks_transfer(admin, alice, alice_wallet, bob_wallet):
    block("wallet_id", str(alice_wallet.id), "compromised", by=admin)
    with pytest.raises(BlockedError):
        initiate_transfer(alice, alice_wallet.id, bob_wallet.id, 1_000, uuid.uuid4())


def test_dynamic_qr_roundtrip(bob_wallet):
    issued = issue_dynamic_qr(bob_wallet, 15_000)
    assert issued["qr_png_base64"]
    intent = decode_dynamic_qr(issued["token"])
    assert intent["recipient_wallet"] == str(bob_wallet.id)
    assert intent["amount"] == 15_000
    assert intent["ref_id"] == issued["ref_id"]


def test_dynamic_qr_is_single_use(alice, alice_wallet, bob_wallet, otp_inbox):
    issued = issue_dynamic_qr(bob_wallet, 15_000)
    intent = decode_dynamic_qr(issued["token"])
    # ref_id becomes the idempotency key -> the unique constraint burns the QR.
    initiate_transfer(alice, alice_wallet.id, bob_wallet.id,
                      intent["amount"], intent["ref_id"])
    with pytest.raises(QRAlreadyUsedError):
        decode_dynamic_qr(issued["token"])


def test_expired_qr_rejected(bob_wallet):
    token = pyjwt.encode(
        {
            "typ": "hamyon.p2p.dynamic",
            "wallet_id": str(bob_wallet.id),
            "amount": 1_000,
            "ref_id": str(uuid.uuid4()),
            "exp": int(time.time()) - 10,
        },
        django_settings.QR_JWT_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(QRInvalidError):
        decode_dynamic_qr(token)


def test_tampered_qr_rejected(bob_wallet):
    token = pyjwt.encode(
        {
            "typ": "hamyon.p2p.dynamic",
            "wallet_id": str(bob_wallet.id),
            "amount": 999_999_999,
            "ref_id": str(uuid.uuid4()),
            "exp": int(time.time()) + 600,
        },
        "attacker-secret-attacker-secret-attacker",
        algorithm="HS256",
    )
    with pytest.raises(QRInvalidError):
        decode_dynamic_qr(token)
