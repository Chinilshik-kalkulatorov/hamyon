from django.http import JsonResponse
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.throttling import ScopedRateThrottle


class ThrottledLogin(ObtainAuthToken):
    """Token login with its own tight per-IP rate limit (anti brute-force).
    Overrides the global throttles so the 'login' scope (see settings
    DEFAULT_THROTTLE_RATES) applies instead of the looser anon rate."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


def api_root(request):
    """Public API index served at the bare domain — a map of the API for
    reviewers, instead of a bare 404."""
    return JsonResponse(
        {
            "service": "Hamyon — ledger wallet API",
            "status": "ok",
            "source": "https://github.com/Chinilshik-kalkulatorov/hamyon",
            "admin": "/admin/",
            "endpoints": {
                "obtain_token": "POST /api/auth/token/",
                "wallets": "GET, POST /api/wallet/",
                "balance": "GET /api/wallet/{id}/balance/",
                "history": "GET /api/wallet/{id}/history/",
                "payments": "POST /api/payments/initiate/ , /{id}/confirm/ , /{id}/cancel/",
                "p2p_transfer": "POST /api/p2p/transfer/ , /transfers/{id}/confirm/",
                "qr": "POST /api/p2p/qr/dynamic/ , /api/p2p/scan/",
                "kyc": "POST /api/kyc/submit/ , GET /api/kyc/status/",
                "blacklist": "POST /api/admin/blacklist/block/ , /{id}/unblock/",
            },
        },
        json_dumps_params={"indent": 2, "ensure_ascii": False},
    )
