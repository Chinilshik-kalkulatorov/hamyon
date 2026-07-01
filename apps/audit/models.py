from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only trail of mutating API calls: who / what / when / result.

    Metadata only — request bodies are never stored, so OTP codes, amounts and
    credentials never land here. `username` is denormalised so the row survives
    even if the user is later deleted.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    username = models.CharField(max_length=150, blank=True, default="")
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=255)
    status_code = models.PositiveSmallIntegerField(default=0)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"], name="audit_created_idx")]

    def __str__(self):
        return f"{self.username or 'anon'} {self.method} {self.path} [{self.status_code}]"
