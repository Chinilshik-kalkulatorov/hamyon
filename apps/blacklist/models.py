import uuid

from django.conf import settings
from django.db import models


class BlacklistEntry(models.Model):
    """One block event. The row itself is the audit record: who, when, why —
    and, after unblocking, who lifted it and why. Rows are never deleted."""

    class TargetType(models.TextChoices):
        USER_ID = "user_id", "User id"
        PHONE = "phone", "Phone"
        WALLET_ID = "wallet_id", "Wallet id"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target_type = models.CharField(max_length=16, choices=TargetType.choices)
    target_value = models.CharField(max_length=64)
    reason = models.TextField()
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    unblocked_at = models.DateTimeField(null=True, blank=True)
    unblocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    unblock_reason = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["target_type", "target_value"], name="blacklist_target_idx"),
        ]
        ordering = ["-created_at"]

    @property
    def is_active(self) -> bool:
        return self.unblocked_at is None

    def __str__(self):
        state = "active" if self.is_active else "lifted"
        return f"[{state}] {self.target_type}={self.target_value}"
