from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.models import LedgerEntry

from .tasks import send_ledger_push


@receiver(post_save, sender=LedgerEntry)
def push_after_ledger_event(sender, instance, created, **kwargs):
    if not created:
        return
    entry_id = str(instance.id)
    # on_commit: never notify about a transaction that rolled back.
    transaction.on_commit(lambda: send_ledger_push.delay(entry_id))
