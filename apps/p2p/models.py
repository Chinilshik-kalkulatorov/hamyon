import uuid

from django.db import models

from apps.core.models import Transfer, Wallet
from apps.core.state import StateMachineMixin


class TransferRequest(StateMachineMixin, models.Model):
    """P2P transfer intent awaiting the sender's OTP confirmation.

    The actual money movement (debit + credit + core.Transfer) happens only on
    confirm, in one atomic transaction.

    For transfers initiated from a dynamic QR, idempotency_key == the QR's
    ref_id — the unique constraint makes the QR single-use at the DB level.
    """

    class Status(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        OTP_PENDING = "otp_pending", "OTP pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    ALLOWED = {
        Status.INITIATED: {Status.OTP_PENDING, Status.CANCELLED, Status.EXPIRED},
        Status.OTP_PENDING: {Status.CONFIRMED, Status.CANCELLED, Status.EXPIRED},
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender_wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="+")
    recipient_wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="+")
    amount = models.BigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INITIATED)
    idempotency_key = models.UUIDField(unique=True)
    transfer = models.OneToOneField(Transfer, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="request")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (f"{self.sender_wallet_id} -> {self.recipient_wallet_id} "
                f"{self.amount} [{self.status}]")
