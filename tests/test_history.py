import pytest
from django.utils import timezone

from apps.core.models import LedgerEntry
from apps.core.services.ledger import post_entry

pytestmark = pytest.mark.django_db


@pytest.fixture
def filled_wallet(bob_wallet):
    """25 entries; five of them share one timestamp to exercise the id tie-break."""
    shared_ts = timezone.now()
    for i in range(25):
        entry = LedgerEntry(
            wallet=bob_wallet,
            type=LedgerEntry.Type.CREDIT,
            amount=1_000 + i,
        )
        if i < 5:
            entry.created_at = shared_ts
        entry.save()
    return bob_wallet


def test_cursor_walk_visits_every_entry_once(bob, filled_wallet, auth_client):
    client = auth_client(bob)
    seen, cursor, pages = [], None, 0

    while True:
        url = f"/api/wallet/{filled_wallet.id}/history/?page_size=10"
        if cursor:
            url += f"&cursor={cursor}"
        response = client.get(url)
        assert response.status_code == 200
        seen.extend(item["id"] for item in response.data["results"])
        pages += 1
        cursor = response.data["next_cursor"]
        if not cursor:
            break

    assert pages == 3  # 10 + 10 + 5
    assert len(seen) == 25
    assert len(set(seen)) == 25  # stable under ties: no duplicates, no gaps


def test_history_runs_exactly_two_queries(bob, filled_wallet, auth_client,
                                          django_assert_num_queries):
    """Ownership check + one seek query. A COUNT(*) (offset pagination) would
    make this fail — offset pagination is banned."""
    client = auth_client(bob)
    with django_assert_num_queries(2):
        response = client.get(f"/api/wallet/{filled_wallet.id}/history/?page_size=10")
    assert response.status_code == 200


def test_filter_by_type_and_status(bob, bob_wallet, auth_client):
    credit = post_entry(bob_wallet, LedgerEntry.Type.CREDIT, 5_000)
    hold = post_entry(bob_wallet, LedgerEntry.Type.HOLD, 2_000)
    client = auth_client(bob)

    by_type = client.get(f"/api/wallet/{bob_wallet.id}/history/?type=hold")
    assert [item["id"] for item in by_type.data["results"]] == [str(hold.id)]
    assert by_type.data["results"][0]["status"] == "pending"

    post_entry(bob_wallet, LedgerEntry.Type.REVERSAL, 2_000, related_entry=hold)
    released = client.get(f"/api/wallet/{bob_wallet.id}/history/?status=released")
    assert [item["id"] for item in released.data["results"]] == [str(hold.id)]

    posted = client.get(f"/api/wallet/{bob_wallet.id}/history/?status=posted")
    assert str(credit.id) in [item["id"] for item in posted.data["results"]]


def test_foreign_wallet_history_is_404(alice, bob_wallet, auth_client):
    response = auth_client(alice).get(f"/api/wallet/{bob_wallet.id}/history/")
    assert response.status_code == 404


def test_invalid_cursor_is_400(bob, bob_wallet, auth_client):
    response = auth_client(bob).get(
        f"/api/wallet/{bob_wallet.id}/history/?cursor=garbage!!!"
    )
    assert response.status_code == 400


def test_export_writes_csv_and_sends_link(bob, bob_wallet, settings, tmp_path,
                                          monkeypatch):
    from apps.history.tasks import export_wallet_history

    settings.MEDIA_ROOT = tmp_path
    sent = []
    monkeypatch.setattr("apps.notifications.telegram.send_telegram_push",
                        lambda chat_id, text: sent.append(text) or True)

    post_entry(bob_wallet, LedgerEntry.Type.CREDIT, 9_000)
    url = export_wallet_history(str(bob_wallet.id), bob.pk)

    exports = list((tmp_path / "exports").glob("*.csv"))
    assert len(exports) == 1
    lines = exports[0].read_text().strip().splitlines()
    assert len(lines) == 2  # header + one entry
    assert "9000" in lines[1]
    assert sent and url in sent[0]
