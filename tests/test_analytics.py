import uuid

import pytest

from apps.core.models import LedgerEntry, Transfer
from apps.core.services.ledger import post_entry

pytestmark = pytest.mark.django_db


def _transfer(sender_wallet, recipient_wallet, amount):
    """Create both legs + the Transfer link, the way the P2P service does."""
    debit = post_entry(sender_wallet, LedgerEntry.Type.DEBIT, amount)
    credit = post_entry(recipient_wallet, LedgerEntry.Type.CREDIT, amount)
    return Transfer.objects.create(
        sender_wallet=sender_wallet,
        recipient_wallet=recipient_wallet,
        debit_entry=debit,
        credit_entry=credit,
        amount=amount,
        idempotency_key=uuid.uuid4(),
    )


@pytest.fixture
def scenario(alice_wallet, bob_wallet):
    # alice_wallet already has a 100_000 topup (CREDIT) from conftest.
    post_entry(alice_wallet, LedgerEntry.Type.DEBIT, 30_000)   # cash-out (not a transfer) -> withdraw
    _transfer(alice_wallet, bob_wallet, 20_000)   # alice -> bob : sent
    _transfer(bob_wallet, alice_wallet, 5_000)    # bob -> alice : received
    return alice_wallet


def test_analytics_classifies_and_totals(alice, scenario, auth_client):
    client = auth_client(alice)
    r = client.get(f"/api/wallet/{scenario.id}/analytics/")
    assert r.status_code == 200
    data = r.data

    assert data["in_total"] == 105_000   # 100_000 topup + 5_000 received
    assert data["out_total"] == 50_000   # 30_000 withdraw + 20_000 sent
    assert data["net"] == 55_000

    bd = {row["key"]: row for row in data["breakdown"]}
    assert bd["topup"]["total"] == 100_000
    assert bd["received"]["total"] == 5_000
    assert bd["withdraw"]["total"] == 30_000
    assert bd["sent"]["total"] == 20_000
    assert bd["sent"]["count"] == 1


def test_top_counterparties(alice, scenario, auth_client):
    client = auth_client(alice)
    data = client.get(f"/api/wallet/{scenario.id}/analytics/").data
    cps = data["top_counterparties"]
    assert len(cps) == 1
    assert cps[0]["username"] == "bob"
    assert cps[0]["sent"] == 20_000
    assert cps[0]["received"] == 5_000


def test_daily_series_spans_requested_days(alice, alice_wallet, auth_client):
    client = auth_client(alice)
    data = client.get(f"/api/wallet/{alice_wallet.id}/analytics/?days=7").data
    assert data["days"] == 7
    assert len(data["daily"]) == 8          # inclusive of both endpoints
    assert sum(d["in"] for d in data["daily"]) == 100_000


def test_kyc_block_reflects_spending(alice, scenario, auth_client):
    client = auth_client(alice)
    kyc = client.get(f"/api/wallet/{scenario.id}/analytics/").data["kyc"]
    assert kyc["level"] == "full"
    assert kyc["spent_30d"] == 50_000       # both DEBIT legs count as spend
    assert kyc["remaining_30d"] == kyc["limit_30d"] - 50_000


def test_analytics_extras(alice, scenario, auth_client):
    data = auth_client(alice).get(f"/api/wallet/{scenario.id}/analytics/").data
    assert data["balance"] == 55_000          # 105_000 in − 50_000 out
    assert data["biggest_in"] == 100_000      # the topup
    assert data["biggest_out"] == 30_000      # the cash-out
    assert data["prev_in_total"] == 0         # nothing in the previous window
    assert data["prev_out_total"] == 0
    assert data["active_days"] == 1           # all created today


def test_analytics_is_owner_scoped(bob, alice_wallet, auth_client):
    """A stranger gets 404, not someone else's analytics."""
    r = auth_client(bob).get(f"/api/wallet/{alice_wallet.id}/analytics/")
    assert r.status_code == 404
