"""Account-level endpoints for the authenticated user."""

import re

from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User


class TelegramChatIDSerializer(serializers.Serializer):
    telegram_chat_id = serializers.CharField(max_length=64)

    def validate_telegram_chat_id(self, value):
        value = value.strip()
        if not re.fullmatch(r"-?\d+", value):
            raise serializers.ValidationError("must be a numeric Telegram chat id")
        return value


class RegisterTelegramView(APIView):
    """Bind the caller's Telegram chat to their account so OTP codes are
    delivered to that chat.

    The chat id is read by the bot from the Telegram update (not typed by the
    user), so it is authentic; the API token proves the account. The mapping is
    kept one-to-one: binding a chat detaches it from any other user, so the same
    phone/Telegram can re-login as a different account and OTPs follow.
    """

    def post(self, request):
        serializer = TelegramChatIDSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chat_id = serializer.validated_data["telegram_chat_id"]

        User.objects.filter(telegram_chat_id=chat_id).exclude(
            pk=request.user.pk
        ).update(telegram_chat_id="")
        request.user.telegram_chat_id = chat_id
        request.user.save(update_fields=["telegram_chat_id"])
        return Response({"status": "ok", "telegram_chat_id": chat_id})

    def delete(self, request):
        """Unbind: stop delivering OTP to Telegram for this account."""
        request.user.telegram_chat_id = ""
        request.user.save(update_fields=["telegram_chat_id"])
        return Response(status=status.HTTP_204_NO_CONTENT)
