import pytest

from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db


def test_mutating_call_is_audited(alice, auth_client):
    r = auth_client(alice).post("/api/wallet/")
    assert r.status_code == 201
    entry = AuditLog.objects.filter(path="/api/wallet/", method="POST").first()
    assert entry is not None
    assert entry.username == "alice"      # DRF-authenticated user captured
    assert entry.status_code == 201


def test_reads_are_not_audited(alice, alice_wallet, auth_client):
    AuditLog.objects.all().delete()
    auth_client(alice).get(f"/api/wallet/{alice_wallet.id}/balance/")
    assert AuditLog.objects.count() == 0  # only mutating methods are logged
