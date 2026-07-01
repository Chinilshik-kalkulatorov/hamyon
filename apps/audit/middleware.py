"""Records every mutating API call to the AuditLog table.

Runs in the response phase on purpose: by then DRF has authenticated the
request (its `user` setter also writes the underlying Django request.user), so
token-authenticated callers are captured correctly. Only metadata is stored —
never request bodies.
"""

import logging

log = logging.getLogger("hamyon.audit")

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._record(request, response)
        except Exception:  # noqa: BLE001 — auditing must never break a request
            log.exception("audit record failed")
        return response

    def _record(self, request, response):
        if request.method not in MUTATING or not request.path.startswith("/api/"):
            return
        from .models import AuditLog

        user = getattr(request, "user", None)
        authed = bool(user and getattr(user, "is_authenticated", False))
        AuditLog.objects.create(
            user=user if authed else None,
            username=user.get_username() if authed else "",
            method=request.method,
            path=request.path[:255],
            status_code=getattr(response, "status_code", 0),
            ip=self._client_ip(request),
        )

    @staticmethod
    def _client_ip(request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if xff:
            return xff.split(",")[0].strip()[:45]
        return request.META.get("REMOTE_ADDR")
