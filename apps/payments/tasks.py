from celery import shared_task
from django.utils import timezone


@shared_task
def expire_stale_requests():
    """Beat task (every minute): expire overdue payment and transfer requests,
    releasing any holds via reversal entries."""
    from apps.p2p.models import TransferRequest
    from apps.p2p.services import expire_transfer_request

    from .models import PaymentRequest
    from .services import expire_request

    now = timezone.now()
    stale_payments = PaymentRequest.objects.filter(
        status__in=[PaymentRequest.Status.INITIATED, PaymentRequest.Status.OTP_PENDING],
        expires_at__lt=now,
    ).values_list("id", flat=True)
    for request_id in stale_payments:
        expire_request(request_id)

    stale_transfers = TransferRequest.objects.filter(
        status__in=[TransferRequest.Status.INITIATED, TransferRequest.Status.OTP_PENDING],
        expires_at__lt=now,
    ).values_list("id", flat=True)
    for request_id in stale_transfers:
        expire_transfer_request(request_id)

    return {"payments": len(stale_payments), "transfers": len(stale_transfers)}
