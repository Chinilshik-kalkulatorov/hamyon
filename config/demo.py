"""Demo-only helpers for the public showcase deployment.

Everything here is inert unless settings.OTP_DEMO_ECHO is enabled (it is off by
default and is NOT part of the backend-only repo). It lets the public demo be
used end-to-end without a real Telegram bot — it never weakens OTP verification,
which still compares SHA-256 hashes.
"""

from django.conf import settings
from django.http import Http404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.redis import get_redis


class DemoLastOTP(APIView):
    """Return the most recent OTP for the current user (demo mode only)."""

    def get(self, request):
        if not getattr(settings, "OTP_DEMO_ECHO", False):
            raise Http404
        code = get_redis().get(f"demo:otp:{request.user.pk}")
        return Response({"code": code})
