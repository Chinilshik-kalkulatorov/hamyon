from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import InvalidTransition
from apps.core.models import LedgerEntry, Wallet
from apps.core.services.guards import run_guards
from apps.core.services.ledger import post_entry
from apps.otp.service import send_otp, verify_otp

from .models import PaymentRequest


def _otp_purpose(payment_request: PaymentRequest) -> str:
    return ("withdraw" if payment_request.direction == PaymentRequest.Direction.WITHDRAW
            else "payment")


def initiate_payment(user, wallet_id, direction, amount, idempotency_key):
    """Returns (request, created). Retrying with the same idempotency key
    returns the existing request without creating duplicates."""
    existing = PaymentRequest.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing, False

    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(id=wallet_id, user=user)
        is_withdraw = direction == PaymentRequest.Direction.WITHDRAW
        # Guards in brief order: blacklist -> KYC -> balance/limit.
        run_guards(user, wallet, amount, spends_funds=is_withdraw)

        try:
            with transaction.atomic():  # savepoint: keep outer tx usable on conflict
                request = PaymentRequest.objects.create(
                    wallet=wallet,
                    direction=direction,
                    amount=amount,
                    idempotency_key=idempotency_key,
                    expires_at=timezone.now()
                    + timezone.timedelta(seconds=settings.PAYMENT_REQUEST_TTL_SECONDS),
                )
        except IntegrityError:
            # Concurrent retry with the same key won the race: return its result.
            return PaymentRequest.objects.get(idempotency_key=idempotency_key), False

        if is_withdraw:
            # Reserve the funds: hold reduces `available` until confirm/cancel.
            hold = post_entry(wallet, LedgerEntry.Type.HOLD, amount)
            request.hold_entry = hold
            request.save(update_fields=["hold_entry", "updated_at"])

        request.transition_to(PaymentRequest.Status.OTP_PENDING)

    # After commit only: never send an OTP for a transaction that rolled back.
    transaction.on_commit(lambda: send_otp(user, _otp_purpose(request)))
    return request, True


def confirm_payment(user, request_id, code):
    """Verify the OTP, then write the real ledger entries atomically."""
    request = PaymentRequest.objects.get(id=request_id, wallet__user=user)
    if request.status != PaymentRequest.Status.OTP_PENDING:
        raise InvalidTransition(
            f"PaymentRequest: cannot confirm from status {request.status}"
        )

    # Burn the OTP first; raises on wrong/expired/locked code.
    verify_otp(user, _otp_purpose(request), code)

    expired = False
    with transaction.atomic():
        request = PaymentRequest.objects.select_for_update().get(id=request_id)
        wallet = Wallet.objects.select_for_update().get(id=request.wallet_id)
        if request.status != PaymentRequest.Status.OTP_PENDING:
            raise InvalidTransition("PaymentRequest: already finalized")

        if request.expires_at < timezone.now():
            # NB: no raise inside the atomic block after these writes —
            # an exception here would roll back the expiry itself.
            _release_hold(request)
            request.transition_to(PaymentRequest.Status.EXPIRED)
            expired = True
        else:
            if request.direction == PaymentRequest.Direction.WITHDRAW:
                result = post_entry(wallet, LedgerEntry.Type.DEBIT, request.amount)
                _release_hold(request)
            else:
                result = post_entry(wallet, LedgerEntry.Type.CREDIT, request.amount)
            request.result_entry = result
            request.transition_to(PaymentRequest.Status.CONFIRMED,
                                  extra_update_fields=["result_entry"])

    if expired:
        raise InvalidTransition("PaymentRequest: expired before confirmation")
    return request


def cancel_payment(user, request_id):
    with transaction.atomic():
        request = PaymentRequest.objects.select_for_update().get(
            id=request_id, wallet__user=user
        )
        request.transition_to(PaymentRequest.Status.CANCELLED)
        _release_hold(request)
    return request


def expire_request(request_id):
    """Idempotent single-request expiry used by the Celery beat task."""
    with transaction.atomic():
        request = PaymentRequest.objects.select_for_update().get(id=request_id)
        if request.status not in (PaymentRequest.Status.INITIATED,
                                  PaymentRequest.Status.OTP_PENDING):
            return None
        if request.expires_at >= timezone.now():
            return None
        request.transition_to(PaymentRequest.Status.EXPIRED)
        _release_hold(request)
    return request


def _release_hold(request: PaymentRequest):
    """Holds are released by a reversal entry — the hold row itself is immutable."""
    if request.hold_entry_id is None:
        return
    already_released = LedgerEntry.objects.filter(
        related_entry_id=request.hold_entry_id, type=LedgerEntry.Type.REVERSAL
    ).exists()
    if not already_released:
        post_entry(request.wallet, LedgerEntry.Type.REVERSAL, request.amount,
                   related_entry=request.hold_entry)
