"""The only place that writes ledger entries."""

from apps.core.models import LedgerEntry, Wallet


def post_entry(wallet: Wallet, entry_type: str, amount: int, *,
               ref_id=None, related_entry=None) -> LedgerEntry:
    kwargs = {
        "wallet": wallet,
        "type": entry_type,
        "amount": amount,
        "related_entry": related_entry,
    }
    if ref_id is not None:
        kwargs["ref_id"] = ref_id
    return LedgerEntry.objects.create(**kwargs)
