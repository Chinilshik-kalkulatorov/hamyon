from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.blacklist.service import is_blocked
from apps.core.exceptions import (
    BlockedError,
    InsufficientFundsError,
    InvalidTransition,
)
from apps.core.models import LedgerEntry, Transfer, Wallet
from apps.core.services.balance import get_wallet_balance
from apps.core.services.guards import run_guards
from apps.core.services.ledger import post_entry
from apps.otp.service import send_otp, verify_otp

from .models import TransferRequest


def initiate_transfer(user, sender_wallet_id, recipient_wallet_id, amount,
                      idempotency_key):
    """Returns (request, created); idempotent on idempotency_key."""
    existing = TransferRequest.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing, False

    sender_wallet = Wallet.objects.get(id=sender_wallet_id, user=user)
    recipient_wallet = Wallet.objects.select_related("user").get(id=recipient_wallet_id)
    if sender_wallet.id == recipient_wallet.id:
        raise InvalidTransition("cannot transfer to the same wallet")

    # Guards for the sender: blacklist -> KYC -> available balance.
    run_guards(user, sender_wallet, amount, spends_funds=True)
    # P2P is blocked if EITHER party is blacklisted.
    if is_blocked(user=recipient_wallet.user, wallet_id=recipient_wallet.id,
                  phone=recipient_wallet.user.phone):
        raise BlockedError()

    try:
        with transaction.atomic():  # savepoint: keep the test/request tx usable
            request = TransferRequest.objects.create(
                sender_wallet=sender_wallet,
                recipient_wallet=recipient_wallet,
                amount=amount,
                idempotency_key=idempotency_key,
                expires_at=timezone.now()
                + timezone.timedelta(seconds=settings.PAYMENT_REQUEST_TTL_SECONDS),
            )
    except IntegrityError:
        return TransferRequest.objects.get(idempotency_key=idempotency_key), False

    request.transition_to(TransferRequest.Status.OTP_PENDING)
    send_otp(user, "p2p")
    return request, True


def confirm_transfer(user, request_id, code):
    """Sender's OTP, then debit + credit + Transfer in ONE atomic transaction.
    If either entry fails, everything rolls back."""
    request = TransferRequest.objects.get(id=request_id, sender_wallet__user=user)
    if request.status != TransferRequest.Status.OTP_PENDING:
        raise InvalidTransition(
            f"TransferRequest: cannot confirm from status {request.status}"
        )

    verify_otp(user, "p2p", code)

    outcome = "ok"
    with transaction.atomic():
        request = TransferRequest.objects.select_for_update().get(id=request_id)
        if request.status != TransferRequest.Status.OTP_PENDING:
            raise InvalidTransition("TransferRequest: already finalized")

        if request.expires_at < timezone.now():
            # No raise after this write inside the atomic block — it would
            # roll the expiry back.
            request.transition_to(TransferRequest.Status.EXPIRED)
            outcome = "expired"
        else:
            # Lock both wallets in a stable order (by pk) to avoid deadlocks.
            wallets = {
                w.id: w
                for w in Wallet.objects.select_for_update()
                .filter(id__in=[request.sender_wallet_id, request.recipient_wallet_id])
                .order_by("id")
            }
            sender = wallets[request.sender_wallet_id]
            recipient = wallets[request.recipient_wallet_id]

            # Re-check under the lock, bypassing the cache: a 5s-cached number
            # must never authorize a debit.
            available = get_wallet_balance(sender.id, use_cache=False)["available"]
            if available < request.amount:
                request.transition_to(TransferRequest.Status.CANCELLED)
                outcome = "insufficient"
            else:
                debit = post_entry(sender, LedgerEntry.Type.DEBIT, request.amount)
                credit = post_entry(recipient, LedgerEntry.Type.CREDIT, request.amount)
                transfer = Transfer.objects.create(
                    sender_wallet=sender,
                    recipient_wallet=recipient,
                    debit_entry=debit,
                    credit_entry=credit,
                    amount=request.amount,
                    idempotency_key=request.idempotency_key,
                )
                request.transfer = transfer
                request.transition_to(TransferRequest.Status.CONFIRMED,
                                      extra_update_fields=["transfer"])

    if outcome == "expired":
        raise InvalidTransition("TransferRequest: expired before confirmation")
    if outcome == "insufficient":
        raise InsufficientFundsError()
    return request


def expire_transfer_request(request_id):
    with transaction.atomic():
        request = TransferRequest.objects.select_for_update().get(id=request_id)
        if request.status not in (TransferRequest.Status.INITIATED,
                                  TransferRequest.Status.OTP_PENDING):
            return None
        if request.expires_at >= timezone.now():
            return None
        request.transition_to(TransferRequest.Status.EXPIRED)
    return request
