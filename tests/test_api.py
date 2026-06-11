import uuid

import pytest
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.blacklist.service import block, is_blocked, unblock
from apps.core.models import LedgerEntry
from apps.core.services.ledger import post_entry
from apps.kyc.models import KYCApplication

pytestmark = pytest.mark.django_db


def test_balance_endpoint_read_only(alice, alice_wallet, auth_client):
    client = auth_client(alice)
    entries_before = LedgerEntry.objects.count()
    response = client.get(f"/api/wallet/{alice_wallet.id}/balance/")
    assert response.status_code == 200
    assert response.data["balance"] == 100_000
    assert response.data["available"] == 100_000
    assert LedgerEntry.objects.count() == entries_before  # never modifies anything


def test_balance_of_foreign_wallet_is_404(bob, alice_wallet, auth_client):
    response = auth_client(bob).get(f"/api/wallet/{alice_wallet.id}/balance/")
    assert response.status_code == 404


def test_blacklist_middleware_returns_empty_403(admin, alice, alice_wallet, bob_wallet):
    block("user_id", str(alice.pk), "court order", by=admin)

    client = APIClient()
    token, _ = Token.objects.get_or_create(user=alice)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    response = client.post("/api/p2p/transfer/", {
        "sender_wallet": str(alice_wallet.id),
        "recipient_wallet": str(bob_wallet.id),
        "amount": 1_000,
        "idempotency_key": str(uuid.uuid4()),
    }, format="json")

    assert response.status_code == 403
    assert response.content == b""  # no detail leaked


def test_blocked_wallet_in_body_also_403(admin, alice, alice_wallet, bob_wallet):
    block("wallet_id", str(bob_wallet.id), "mule wallet", by=admin)

    client = APIClient()
    token, _ = Token.objects.get_or_create(user=alice)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    response = client.post("/api/p2p/transfer/", {
        "sender_wallet": str(alice_wallet.id),
        "recipient_wallet": str(bob_wallet.id),
        "amount": 1_000,
        "idempotency_key": str(uuid.uuid4()),
    }, format="json")

    assert response.status_code == 403
    assert response.content == b""


def test_unblock_restores_access_and_keeps_audit(admin, alice):
    entry = block("user_id", str(alice.pk), "test", by=admin)
    assert is_blocked(user=alice)
    unblock(entry, reason="false positive", by=admin)
    assert not is_blocked(user=alice)
    entry.refresh_from_db()
    assert entry.unblocked_at is not None
    assert entry.unblock_reason == "false positive"
    with pytest.raises(ValueError):
        unblock(entry, reason="again", by=admin)


def test_payment_e2e_through_api(alice, alice_wallet, auth_client, otp_inbox,
                                 django_capture_on_commit_callbacks):
    client = auth_client(alice)
    key = str(uuid.uuid4())

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post("/api/payments/initiate/", {
            "wallet_id": str(alice_wallet.id),
            "direction": "topup",
            "amount": 30_000,
            "idempotency_key": key,
        }, format="json")
    assert response.status_code == 201

    # Idempotent retry returns the same request with 200.
    retry = client.post("/api/payments/initiate/", {
        "wallet_id": str(alice_wallet.id),
        "direction": "topup",
        "amount": 30_000,
        "idempotency_key": key,
    }, format="json")
    assert retry.status_code == 200
    assert retry.data["id"] == response.data["id"]

    wrong_code = "000000" if otp_inbox[-1] != "000000" else "111111"
    bad = client.post(f"/api/payments/{response.data['id']}/confirm/",
                      {"code": wrong_code}, format="json")
    assert bad.status_code == 400 and bad.data["code"] == "otp_invalid"

    good = client.post(f"/api/payments/{response.data['id']}/confirm/",
                       {"code": otp_inbox[-1]}, format="json")
    assert good.status_code == 200 and good.data["status"] == "confirmed"

    balance = client.get(f"/api/wallet/{alice_wallet.id}/balance/")
    assert balance.data["balance"] == 130_000


def test_kyc_approve_via_admin_endpoint(admin, bob, auth_client):
    bob_client = auth_client(bob)
    submitted = bob_client.post("/api/kyc/submit/", {
        "requested_level": "full",
        "passport_ref": "s3://kyc/bob/passport.jpg",
        "selfie_ref": "s3://kyc/bob/selfie.jpg",
    }, format="json")
    assert submitted.status_code == 201

    # A second application while one is pending is rejected.
    again = bob_client.post("/api/kyc/submit/", {
        "requested_level": "full",
        "passport_ref": "x", "selfie_ref": "y",
    }, format="json")
    assert again.status_code == 400

    approved = auth_client(admin).post(
        f"/api/kyc/admin/{submitted.data['id']}/approve/", format="json"
    )
    assert approved.status_code == 200

    bob.refresh_from_db()
    assert bob.kyc_level == "full"
    status = bob_client.get("/api/kyc/status/")
    assert status.data["level"] == "full"


def test_kyc_reject_requires_reason_and_is_final(admin, bob, auth_client):
    app = KYCApplication.objects.create(
        user=bob, requested_level="full", passport_ref="x", selfie_ref="y"
    )
    admin_client = auth_client(admin)

    no_reason = admin_client.post(f"/api/kyc/admin/{app.id}/reject/", {}, format="json")
    assert no_reason.status_code == 400

    rejected = admin_client.post(f"/api/kyc/admin/{app.id}/reject/",
                                 {"reason": "blurry photo"}, format="json")
    assert rejected.status_code == 200

    twice = admin_client.post(f"/api/kyc/admin/{app.id}/approve/", format="json")
    assert twice.status_code == 409  # invalid state transition


def test_dynamic_qr_scan_endpoint(alice, bob, bob_wallet, auth_client):
    issued = auth_client(bob).post("/api/p2p/qr/dynamic/", {
        "wallet_id": str(bob_wallet.id), "amount": 5_000,
    }, format="json")
    assert issued.status_code == 200

    scanned = auth_client(alice).post("/api/p2p/scan/",
                                      {"token": issued.data["token"]}, format="json")
    assert scanned.status_code == 200
    intent = scanned.data["transfer_intent"]
    assert intent["recipient_wallet"] == str(bob_wallet.id)
    assert intent["amount"] == 5_000


def test_static_qr_returns_png(alice, alice_wallet, auth_client):
    response = auth_client(alice).get(f"/api/wallet/{alice_wallet.id}/qr/static/")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_notification_logged_for_transfer(alice, alice_wallet, bob, bob_wallet):
    from apps.core.models import Transfer
    from apps.notifications.models import NotificationLog
    from apps.notifications.tasks import send_ledger_push

    debit = post_entry(alice_wallet, LedgerEntry.Type.DEBIT, 7_000)
    credit = post_entry(bob_wallet, LedgerEntry.Type.CREDIT, 7_000)
    Transfer.objects.create(
        sender_wallet=alice_wallet, recipient_wallet=bob_wallet,
        debit_entry=debit, credit_entry=credit, amount=7_000,
        idempotency_key=uuid.uuid4(),
    )

    send_ledger_push(str(credit.id))
    log = NotificationLog.objects.get(entry=credit)
    assert log.status == "sent"
    assert log.text == "You received 70 UZS from @alice"

    send_ledger_push(str(debit.id))
    assert NotificationLog.objects.get(entry=debit).text == "70 UZS withdrawn."

    # Holds are internal bookkeeping: no push.
    hold = post_entry(alice_wallet, LedgerEntry.Type.HOLD, 1_000)
    send_ledger_push(str(hold.id))
    assert not NotificationLog.objects.filter(entry=hold).exists()
