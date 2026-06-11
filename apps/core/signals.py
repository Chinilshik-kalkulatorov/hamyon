from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import LedgerEntry
from .services.balance import invalidate_balance_cache


@receiver(post_save, sender=LedgerEntry)
def drop_balance_cache(sender, instance, created, **kwargs):
    if created:
        invalidate_balance_cache(instance.wallet_id)
