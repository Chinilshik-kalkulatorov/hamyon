import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.exceptions import (
    InsufficientFundsError,
    InvalidTransition,
    KYCLimitExceededError,
    KYCRejectedError,
)
from apps.core.models import LedgerEntry
from apps.core.services.balance import get_wallet_balance
from apps.kyc.models import KYCApplication
from apps.payments.models import PaymentRequest
from apps.payments.services import (
    cancel_payment,
    confirm_payment,
    expire_request,
    initiate_payment,
)

pytestmark = pytest.mark.django_db

TOPUP = PaymentRequest.Direction.TOPUP
WITHDRAW = PaymentRequest.Direction.WITHDRAW


def balance(wallet):
    return get_wallet_balance(wallet.id, use_cache=False)


def initiate(user, wallet, direction, amount, key=None,
             django_capture_on_commit_callbacks=None):
    key = key or uuid.uuid4()
    return initiate_payment(user, wallet.id, direction, amount, key)


def test_topup_flow_with_otp(alice, alice_wallet, otp_inbox,
                             django_capture_on_commit_callbacks):
    key = uuid.uuid4()
    with django_capture_on_commit_callbacks(execute=True):
        request, created = initiate_payment(alice, alice_wallet.id, TOPUP, 50_000, key)
    assert created and request.status == PaymentRequest.Status.OTP_PENDING
    assert balance(alice_wallet)["balance"] == 100_000  # nothing credited yet

    confirm_payment(alice, request.id, otp_inbox[-1])
    assert balance(alice_wallet)["balance"] == 150_000
    request.refresh_from_db()
    assert request.status == PaymentRequest.Status.CONFIRMED
    assert request.result_entry.type == LedgerEntry.Type.CREDIT


def test_initiate_is_idempotent(alice, alice_wallet, otp_inbox,
                                django_capture_on_commit_callbacks):
    key = uuid.uuid4()
    with django_capture_on_commit_callbacks(execute=True):
        first, created_first = initiate_payment(alice, alice_wallet.id, TOPUP, 50_000, key)
        second, created_second = initiate_payment(alice, alice_wallet.id, TOPUP, 50_000, key)
    assert created_first and not created_second
    assert first.id == second.id
    assert PaymentRequest.objects.filter(idempotency_key=key).count() == 1


def test_withdraw_places_hold_then_confirms(alice, alice_wallet, otp_inbox,
                                            django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        request, _ = initiate_payment(alice, alice_wallet.id, WITHDRAW, 40_000, uuid.uuid4())

    # Hold reserves the funds but does not move them.
    assert balance(alice_wallet) == {"balance": 100_000, "held": 40_000,
                                     "available": 60_000}

    confirm_payment(alice, request.id, otp_inbox[-1])
    # Debit posted, hold released by a reversal.
    assert balance(alice_wallet) == {"balance": 60_000, "held": 0, "available": 60_000}
    types = list(
        LedgerEntry.objects.filter(wallet=alice_wallet)
        .order_by("created_at").values_list("type", flat=True)
    )
    assert types.count(LedgerEntry.Type.HOLD) == 1
    assert types.count(LedgerEntry.Type.REVERSAL) == 1
    assert types.count(LedgerEntry.Type.DEBIT) == 1


def test_cancel_releases_hold(alice, alice_wallet, otp_inbox,
                              django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        request, _ = initiate_payment(alice, alice_wallet.id, WITHDRAW, 40_000, uuid.uuid4())
    assert balance(alice_wallet)["available"] == 60_000

    cancel_payment(alice, request.id)
    request.refresh_from_db()
    assert request.status == PaymentRequest.Status.CANCELLED
    assert balance(alice_wallet) == {"balance": 100_000, "held": 0, "available": 100_000}


def test_expiry_releases_hold(alice, alice_wallet, otp_inbox,
                              django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        request, _ = initiate_payment(alice, alice_wallet.id, WITHDRAW, 40_000, uuid.uuid4())
    PaymentRequest.objects.filter(id=request.id).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    expire_request(request.id)
    request.refresh_from_db()
    assert request.status == PaymentRequest.Status.EXPIRED
    assert balance(alice_wallet)["available"] == 100_000


def test_confirm_twice_is_invalid_transition(alice, alice_wallet, otp_inbox,
                                             django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        request, _ = initiate_payment(alice, alice_wallet.id, TOPUP, 10_000, uuid.uuid4())
    confirm_payment(alice, request.id, otp_inbox[-1])
    with pytest.raises(InvalidTransition):
        confirm_payment(alice, request.id, otp_inbox[-1])


def test_invalid_state_transition_raises():
    request = PaymentRequest(status=PaymentRequest.Status.INITIATED)
    with pytest.raises(InvalidTransition):
        # must pass through otp_pending first
        request.transition_to(PaymentRequest.Status.CONFIRMED)


def test_withdraw_more_than_available_fails(alice, alice_wallet):
    with pytest.raises(InsufficientFundsError):
        initiate_payment(alice, alice_wallet.id, WITHDRAW, 200_000, uuid.uuid4())


def test_kyc_rejected_user_cannot_transact(bob, bob_wallet):
    app = KYCApplication.objects.create(
        user=bob, requested_level="full", passport_ref="x", selfie_ref="y"
    )
    app.reject(by=bob, reason="fake documents")
    with pytest.raises(KYCRejectedError):
        initiate_payment(bob, bob_wallet.id, TOPUP, 1_000, uuid.uuid4())


def test_kyc_spend_limit_enforced(alice, alice_wallet, settings):
    settings.KYC_SPEND_LIMITS = {**settings.KYC_SPEND_LIMITS, "full": 30_000}
    with pytest.raises(KYCLimitExceededError):
        initiate_payment(alice, alice_wallet.id, WITHDRAW, 40_000, uuid.uuid4())
