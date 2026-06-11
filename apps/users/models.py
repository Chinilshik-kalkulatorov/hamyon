from django.contrib.auth.models import AbstractUser
from django.db import models


class KYCLevel(models.TextChoices):
    UNVERIFIED = "unverified", "Unverified"
    BASIC = "basic", "Basic"
    FULL = "full", "Full"


class User(AbstractUser):
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True)
    # Confirmed at account setup, not at send time. Empty = not confirmed yet.
    telegram_chat_id = models.CharField(max_length=64, blank=True, default="")
    kyc_level = models.CharField(
        max_length=16, choices=KYCLevel.choices, default=KYCLevel.UNVERIFIED
    )

    def __str__(self):
        return self.username
