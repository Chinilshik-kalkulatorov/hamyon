import uuid

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.state import StateMachineMixin
from apps.users.models import KYCLevel


class KYCApplication(StateMachineMixin, models.Model):
    """Identity verification request.

    passport_ref / selfie_ref are REFERENCES (e.g. object-storage keys) only —
    the files themselves are never stored in this system.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    ALLOWED = {
        Status.PENDING: {Status.APPROVED, Status.REJECTED},
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="kyc_applications"
    )
    requested_level = models.CharField(
        max_length=16,
        choices=[(KYCLevel.BASIC, "Basic"), (KYCLevel.FULL, "Full")],
        default=KYCLevel.BASIC,
    )
    passport_ref = models.CharField(max_length=255)
    selfie_ref = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reject_reason = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"KYC {self.user} -> {self.requested_level} [{self.status}]"

    @transaction.atomic
    def approve(self, by):
        self.reviewed_by = by
        self.reviewed_at = timezone.now()
        self.transition_to(self.Status.APPROVED,
                           extra_update_fields=["reviewed_by", "reviewed_at"])
        self.user.kyc_level = self.requested_level
        self.user.save(update_fields=["kyc_level"])

    @transaction.atomic
    def reject(self, by, reason: str):
        self.reviewed_by = by
        self.reviewed_at = timezone.now()
        self.reject_reason = reason
        self.transition_to(self.Status.REJECTED,
                           extra_update_fields=["reviewed_by", "reviewed_at", "reject_reason"])
