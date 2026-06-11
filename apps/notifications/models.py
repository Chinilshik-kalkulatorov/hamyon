import uuid

from django.conf import settings
from django.db import models


class NotificationLog(models.Model):
    """Every push attempt is logged: channel, status, timestamp."""

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                             on_delete=models.SET_NULL, related_name="notifications")
    entry = models.ForeignKey("core.LedgerEntry", null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    channel = models.CharField(max_length=16, default="telegram")
    status = models.CharField(max_length=8, choices=Status.choices)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
