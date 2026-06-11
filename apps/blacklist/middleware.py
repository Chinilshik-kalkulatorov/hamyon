"""Blacklist gate: runs before every transaction view (guard #1 of 3).

Blocked actors get an empty 403 — no explanation in the response body.
"""

import json

from django.conf import settings
from django.http import HttpResponse

# Keys in JSON bodies that may carry wallet ids.
_WALLET_BODY_KEYS = ("wallet_id", "wallet", "sender_wallet", "recipient_wallet")


class BlacklistMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_guarded(request) and self._is_blocked(request):
            return HttpResponse(status=403)  # deliberately empty body
        return self.get_response(request)

    def _is_guarded(self, request) -> bool:
        return request.method == "POST" and any(
            request.path.startswith(prefix)
            for prefix in settings.BLACKLIST_GUARDED_PATH_PREFIXES
        )

    def _is_blocked(self, request) -> bool:
        from .service import is_blocked

        user = self._resolve_user(request)
        if user is not None and is_blocked(user=user):
            return True
        for wallet_id in self._wallet_ids_from_body(request):
            if is_blocked(wallet_id=wallet_id):
                return True
        return False

    @staticmethod
    def _resolve_user(request):
        """DRF authenticates at the view layer, which runs after middleware —
        so resolve the token here to vet the actor before the view exists."""
        from rest_framework.authentication import TokenAuthentication

        try:
            result = TokenAuthentication().authenticate(request)
        except Exception:
            return None
        return result[0] if result else None

    @staticmethod
    def _wallet_ids_from_body(request):
        if "json" not in (request.content_type or ""):
            return []
        try:
            data = json.loads(request.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            return []
        if not isinstance(data, dict):
            return []
        return [str(data[key]) for key in _WALLET_BODY_KEYS if data.get(key)]
