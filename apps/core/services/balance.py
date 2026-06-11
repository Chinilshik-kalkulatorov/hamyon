"""Balance is derived, never stored: one aggregated query over the ledger."""

from django.core.cache import cache
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from apps.core.models import LedgerEntry

CACHE_TTL_SECONDS = 5  # brief: maximum 5-second TTL
_CACHE_KEY = "wallet:balance:{wallet_id}"


def get_wallet_balance(wallet_id, use_cache=True):
    """Return {"balance", "held", "available"} computed in ONE DB round-trip.

    Pass use_cache=False inside locked transactions (transfers, withdrawals):
    a financial decision must never be made on a cached number.
    """
    key = _CACHE_KEY.format(wallet_id=wallet_id)
    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            return cached

    t = LedgerEntry.Type
    agg = LedgerEntry.objects.filter(wallet_id=wallet_id).aggregate(
        credit_total=Coalesce(Sum("amount", filter=Q(type=t.CREDIT)), 0),
        debit_total=Coalesce(Sum("amount", filter=Q(type=t.DEBIT)), 0),
        hold_total=Coalesce(Sum("amount", filter=Q(type=t.HOLD)), 0),
        reversal_total=Coalesce(Sum("amount", filter=Q(type=t.REVERSAL)), 0),
    )
    balance = agg["credit_total"] - agg["debit_total"]
    held = agg["hold_total"] - agg["reversal_total"]
    data = {"balance": balance, "held": held, "available": balance - held}
    if use_cache:
        # Never populate the cache from inside a locked transaction.
        cache.set(key, data, CACHE_TTL_SECONDS)
    return data


def invalidate_balance_cache(wallet_id):
    cache.delete(_CACHE_KEY.format(wallet_id=wallet_id))
