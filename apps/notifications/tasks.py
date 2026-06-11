from celery import shared_task


def _format_amount(tiyin: int) -> str:
    whole, frac = divmod(tiyin, 100)
    return f"{whole:,}.{frac:02d}" if frac else f"{whole:,}"


@shared_task
def send_ledger_push(entry_id):
    """Notify the wallet owner about a completed ledger event.

    Runs as a Celery task — never blocks the transaction HTTP response.
    Holds and reversals are internal bookkeeping: no push for them.
    """
    from apps.core.models import LedgerEntry, Transfer

    from .models import NotificationLog
    from .telegram import send_telegram_push

    entry = LedgerEntry.objects.select_related("wallet__user").get(id=entry_id)
    if entry.type not in (LedgerEntry.Type.CREDIT, LedgerEntry.Type.DEBIT):
        return None

    owner = entry.wallet.user
    amount = _format_amount(entry.amount)
    currency = entry.wallet.currency

    if entry.type == LedgerEntry.Type.CREDIT:
        transfer = (
            Transfer.objects.filter(credit_entry=entry)
            .select_related("sender_wallet__user")
            .first()
        )
        if transfer is not None:
            sender = transfer.sender_wallet.user.username
            text = f"You received {amount} {currency} from @{sender}"
        else:
            text = f"You received {amount} {currency}"
    else:
        text = f"{amount} {currency} withdrawn."

    ok = send_telegram_push(owner.telegram_chat_id, text)
    NotificationLog.objects.create(
        user=owner,
        entry=entry,
        channel="telegram",
        status=NotificationLog.Status.SENT if ok else NotificationLog.Status.FAILED,
        text=text,
    )
    return text
