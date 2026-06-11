import pytest

from apps.core.exceptions import ImmutableLedgerError
from apps.core.models import LedgerEntry, Wallet
from apps.core.services.balance import get_wallet_balance
from apps.core.services.ledger import post_entry

pytestmark = pytest.mark.django_db


def test_wallet_has_no_balance_field():
    field_names = {f.name for f in Wallet._meta.get_fields()}
    assert "balance" not in field_names


def test_balance_is_derived_from_entries(alice_wallet):
    post_entry(alice_wallet, LedgerEntry.Type.CREDIT, 20_000)
    post_entry(alice_wallet, LedgerEntry.Type.DEBIT, 5_000)
    info = get_wallet_balance(alice_wallet.id, use_cache=False)
    assert info == {"balance": 115_000, "held": 0, "available": 115_000}


def test_hold_and_reversal_affect_available(alice_wallet):
    hold = post_entry(alice_wallet, LedgerEntry.Type.HOLD, 30_000)
    info = get_wallet_balance(alice_wallet.id, use_cache=False)
    assert info == {"balance": 100_000, "held": 30_000, "available": 70_000}

    post_entry(alice_wallet, LedgerEntry.Type.REVERSAL, 30_000, related_entry=hold)
    info = get_wallet_balance(alice_wallet.id, use_cache=False)
    assert info == {"balance": 100_000, "held": 0, "available": 100_000}


def test_balance_computed_in_one_query(alice_wallet, django_assert_num_queries):
    with django_assert_num_queries(1):
        get_wallet_balance(alice_wallet.id, use_cache=False)


def test_entries_are_append_only(alice_wallet):
    entry = post_entry(alice_wallet, LedgerEntry.Type.CREDIT, 1_000)

    entry.amount = 999
    with pytest.raises(ImmutableLedgerError):
        entry.save()
    with pytest.raises(ImmutableLedgerError):
        entry.delete()
    with pytest.raises(ImmutableLedgerError):
        LedgerEntry.objects.all().update(amount=1)
    with pytest.raises(ImmutableLedgerError):
        LedgerEntry.objects.all().delete()
