import csv
import uuid
from pathlib import Path

from celery import shared_task
from django.conf import settings


@shared_task
def export_wallet_history(wallet_id, user_id):
    """Write the full wallet statement to CSV and send the link via the push
    Telegram channel."""
    from apps.core.models import LedgerEntry
    from apps.notifications.telegram import send_telegram_push
    from apps.users.models import User

    export_dir = Path(settings.MEDIA_ROOT) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{wallet_id}-{uuid.uuid4().hex[:8]}.csv"
    filepath = export_dir / filename

    entries = (
        LedgerEntry.objects.filter(wallet_id=wallet_id)
        .order_by("-created_at", "-id")
        .iterator()
    )
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "type", "amount_tiyin", "ref_id", "related_entry",
                         "created_at"])
        for entry in entries:
            writer.writerow([entry.id, entry.type, entry.amount, entry.ref_id,
                             entry.related_entry_id or "", entry.created_at.isoformat()])

    url = f"{settings.EXPORT_BASE_URL}{settings.MEDIA_URL}exports/{filename}"
    user = User.objects.get(pk=user_id)
    send_telegram_push(user.telegram_chat_id,
                       f"Your Hamyon statement is ready: {url}")
    return url
