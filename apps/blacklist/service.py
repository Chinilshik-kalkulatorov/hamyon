import logging

from django.db.models import Q
from django.utils import timezone

from .models import BlacklistEntry

logger = logging.getLogger("hamyon.blacklist")


def is_blocked(user=None, wallet_id=None, phone=None) -> bool:
    """True if any of the given identities has an active block.

    user_id, phone and wallet_id are independent block targets.
    """
    conditions = Q()
    matched = False
    tt = BlacklistEntry.TargetType

    if user is not None and getattr(user, "is_authenticated", False):
        conditions |= Q(target_type=tt.USER_ID, target_value=str(user.pk))
        matched = True
        phone = phone or user.phone
    if phone:
        conditions |= Q(target_type=tt.PHONE, target_value=phone)
        matched = True
    if wallet_id:
        conditions |= Q(target_type=tt.WALLET_ID, target_value=str(wallet_id))
        matched = True

    if not matched:
        return False
    return BlacklistEntry.objects.filter(conditions, unblocked_at__isnull=True).exists()


def block(target_type: str, target_value: str, reason: str, by) -> BlacklistEntry:
    entry = BlacklistEntry.objects.create(
        target_type=target_type, target_value=str(target_value),
        reason=reason, blocked_by=by,
    )
    logger.info("blacklist.block %s=%s by=%s reason=%s",
                target_type, target_value, by.pk, reason)
    return entry


def unblock(entry: BlacklistEntry, reason: str, by) -> BlacklistEntry:
    """Unblocking always requires a reason; the same row becomes the audit log."""
    if not entry.is_active:
        raise ValueError("Entry is already unblocked")
    entry.unblocked_at = timezone.now()
    entry.unblocked_by = by
    entry.unblock_reason = reason
    entry.save(update_fields=["unblocked_at", "unblocked_by", "unblock_reason"])
    logger.info("blacklist.unblock %s=%s by=%s reason=%s",
                entry.target_type, entry.target_value, by.pk, reason)
    return entry
