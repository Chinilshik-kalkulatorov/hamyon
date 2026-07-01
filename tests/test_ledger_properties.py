"""Property-based checks of the ledger's core invariants (over 52 example-based
tests). The ledger is append-only and the balance is *derived*, so for ANY
sequence of entries the aggregation must equal a manual recompute."""

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.core.models import LedgerEntry, Wallet
from apps.core.services.balance import get_wallet_balance
from apps.core.services.ledger import post_entry
from apps.users.models import User

pytestmark = pytest.mark.django_db

T = LedgerEntry.Type
_ENTRY = st.tuples(
    st.sampled_from([T.CREDIT, T.DEBIT, T.HOLD, T.REVERSAL]),
    st.integers(min_value=1, max_value=1_000_000_000),
)


def _fresh_wallet():
    user = User.objects.create(username="prop_" + uuid.uuid4().hex[:12])
    return Wallet.objects.create(user=user)


@settings(max_examples=60, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(ops=st.lists(_ENTRY, max_size=40))
def test_balance_equals_manual_recompute(ops):
    wallet = _fresh_wallet()
    for typ, amount in ops:
        post_entry(wallet, typ, amount)

    credit = sum(a for t, a in ops if t == T.CREDIT)
    debit = sum(a for t, a in ops if t == T.DEBIT)
    hold = sum(a for t, a in ops if t == T.HOLD)
    reversal = sum(a for t, a in ops if t == T.REVERSAL)

    b = get_wallet_balance(wallet.id, use_cache=False)
    # The three identities that define the ledger (see LedgerEntry docstring).
    assert b["balance"] == credit - debit
    assert b["held"] == hold - reversal
    assert b["available"] == b["balance"] - b["held"]


@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    credits=st.lists(st.integers(min_value=1, max_value=10_000_000), max_size=15),
    debits=st.lists(st.integers(min_value=1, max_value=10_000_000), max_size=15),
)
def test_holds_and_reversals_do_not_change_balance(credits, debits):
    """`balance` reflects only CREDIT/DEBIT; holds/reversals move `held`, never
    the balance. So interleaving holds must leave the balance untouched."""
    wallet = _fresh_wallet()
    for a in credits:
        post_entry(wallet, T.CREDIT, a)
    for a in debits:
        post_entry(wallet, T.DEBIT, a)
    expected = sum(credits) - sum(debits)

    # Now churn holds + their reversals; balance must not move.
    for a in debits or [1]:
        h = post_entry(wallet, T.HOLD, a)
        post_entry(wallet, T.REVERSAL, a, related_entry=h)

    b = get_wallet_balance(wallet.id, use_cache=False)
    assert b["balance"] == expected
    assert b["held"] == 0  # every hold was released
