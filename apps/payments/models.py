import uuid

from django.db import models

from apps.core.models import LedgerEntry, Wallet
from apps.core.state import StateMachineMixin


class PaymentRequest(StateMachineMixin, models.Model):
    """Top-up / withdraw request.

    State machine: initiated -> otp_pending -> confirmed | cancelled | expired.
    Transitions are explicit methods on StateMachineMixin; invalid transitions
    raise InvalidTransition — never silently ignored.
    """

    class Direction(models.TextChoices):
        TOPUP = "topup", "Top-up"
        WITHDRAW = "withdraw", "Withdraw"

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
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="payment_requests")
    direction = models.CharField(max_length=8, choices=Direction.choices)
    amount = models.BigIntegerField(help_text="Tiyin, strictly positive")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INITIATED)
    # Required on every initiate(); retries return the existing request.
    idempotency_key = models.UUIDField(unique=True)
    hold_entry = models.ForeignKey(LedgerEntry, null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="+")
    result_entry = models.ForeignKey(LedgerEntry, null=True, blank=True,
                                     on_delete=models.PROTECT, related_name="+")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.direction} {self.amount} [{self.status}]"
