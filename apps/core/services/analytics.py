"""Spending analytics derived from the ledger (no stored aggregates).

There are no merchant/category fields in this system, so "where money went"
is reconstructed from operation type + the P2P Transfer links:

    CREDIT that is a Transfer credit-leg  -> received (P2P in)
    CREDIT otherwise                      -> topup    (card top-up)
    DEBIT  that is a Transfer debit-leg   -> sent     (P2P out)
    DEBIT  otherwise                      -> withdraw (cash-out)

HOLD / REVERSAL are internal reservations and never count as money movement.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.core.models import LedgerEntry, Transfer, Wallet


def get_wallet_analytics(wallet_id, days: int = 30) -> dict:
    days = max(1, min(int(days), 365))
    now = timezone.now()
    start = now - timedelta(days=days)
    t = LedgerEntry.Type

    entries = LedgerEntry.objects.filter(wallet_id=wallet_id, created_at__gte=start)
    agg = entries.aggregate(
        credit_total=Coalesce(Sum("amount", filter=Q(type=t.CREDIT)), 0),
        debit_total=Coalesce(Sum("amount", filter=Q(type=t.DEBIT)), 0),
        credit_n=Count("id", filter=Q(type=t.CREDIT)),
        debit_n=Count("id", filter=Q(type=t.DEBIT)),
    )

    sent = Transfer.objects.filter(sender_wallet_id=wallet_id, created_at__gte=start).aggregate(
        total=Coalesce(Sum("amount"), 0), n=Count("id")
    )
    received = Transfer.objects.filter(
        recipient_wallet_id=wallet_id, created_at__gte=start
    ).aggregate(total=Coalesce(Sum("amount"), 0), n=Count("id"))

    # Everything that is a CREDIT but not a P2P credit-leg is a top-up; likewise
    # for DEBIT vs sent. Clamp at 0 in case of any timestamp skew at the edges.
    topup_total = max(0, agg["credit_total"] - received["total"])
    topup_n = max(0, agg["credit_n"] - received["n"])
    withdraw_total = max(0, agg["debit_total"] - sent["total"])
    withdraw_n = max(0, agg["debit_n"] - sent["n"])

    breakdown = [
        {"key": "topup", "total": topup_total, "count": topup_n},
        {"key": "received", "total": received["total"], "count": received["n"]},
        {"key": "withdraw", "total": withdraw_total, "count": withdraw_n},
        {"key": "sent", "total": sent["total"], "count": sent["n"]},
    ]

    return {
        "days": days,
        "in_total": agg["credit_total"],
        "out_total": agg["debit_total"],
        "net": agg["credit_total"] - agg["debit_total"],
        "in_count": agg["credit_n"],
        "out_count": agg["debit_n"],
        "breakdown": breakdown,
        "top_counterparties": _top_counterparties(wallet_id, start),
        "daily": _daily_series(entries, start, now, t),
        "kyc": _kyc_block(wallet_id),
    }


def _top_counterparties(wallet_id, start, limit: int = 5) -> list:
    """Combine sent + received per other party (by username)."""
    parties: dict[str, dict] = {}

    out = (
        Transfer.objects.filter(sender_wallet_id=wallet_id, created_at__gte=start)
        .values(name=models_username("recipient_wallet"))
        .annotate(total=Sum("amount"), n=Count("id"))
    )
    for row in out:
        p = parties.setdefault(row["name"], {"username": row["name"], "sent": 0, "received": 0})
        p["sent"] = row["total"]

    inc = (
        Transfer.objects.filter(recipient_wallet_id=wallet_id, created_at__gte=start)
        .values(name=models_username("sender_wallet"))
        .annotate(total=Sum("amount"), n=Count("id"))
    )
    for row in inc:
        p = parties.setdefault(row["name"], {"username": row["name"], "sent": 0, "received": 0})
        p["received"] = row["total"]

    ranked = sorted(parties.values(), key=lambda p: p["sent"] + p["received"], reverse=True)
    return ranked[:limit]


def models_username(prefix: str):
    """Tiny helper so .values(name=F('...__user__username')) reads cleanly."""
    from django.db.models import F

    return F(f"{prefix}__user__username")


def _daily_series(entries, start, now, t) -> list:
    rows = (
        entries.filter(type__in=[t.CREDIT, t.DEBIT])
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(
            cin=Coalesce(Sum("amount", filter=Q(type=t.CREDIT)), 0),
            cout=Coalesce(Sum("amount", filter=Q(type=t.DEBIT)), 0),
        )
    )
    by_day = {r["d"]: r for r in rows}
    series = []
    day = start.date()
    end = now.date()
    while day <= end:
        r = by_day.get(day)
        series.append({
            "date": day.isoformat(),
            "in": r["cin"] if r else 0,
            "out": r["cout"] if r else 0,
        })
        day += timedelta(days=1)
    return series


def _kyc_block(wallet_id) -> dict:
    from apps.kyc.services import get_spending_limit

    wallet = Wallet.objects.select_related("user").get(id=wallet_id)
    user = wallet.user
    limit = get_spending_limit(user)
    window_start = timezone.now() - timedelta(days=settings.KYC_LIMIT_WINDOW_DAYS)
    spent = LedgerEntry.objects.filter(
        wallet__user=user,
        type=LedgerEntry.Type.DEBIT,
        created_at__gte=window_start,
    ).aggregate(total=Coalesce(Sum("amount"), 0))["total"]
    return {
        "level": user.kyc_level,
        "limit_30d": limit,
        "spent_30d": spent,
        "remaining_30d": max(0, limit - spent),
        "window_days": settings.KYC_LIMIT_WINDOW_DAYS,
    }
