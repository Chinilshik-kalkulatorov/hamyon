import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db


def test_demo_otp_hidden_by_default(alice, auth_client):
    """OTP_DEMO_ECHO is off by default → the demo echo endpoint must 404."""
    r = auth_client(alice).get("/api/demo/last-otp/")
    assert r.status_code == 404


@override_settings(OTP_DEMO_ECHO=True)
def test_demo_otp_available_only_in_demo_mode(alice, auth_client):
    r = auth_client(alice).get("/api/demo/last-otp/")
    assert r.status_code == 200
