from rest_framework import serializers

from .models import TransferRequest


class TransferRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransferRequest
        fields = ["id", "sender_wallet", "recipient_wallet", "amount", "status",
                  "idempotency_key", "expires_at", "created_at"]


class TransferInitiateSerializer(serializers.Serializer):
    """Either pass qr_token (dynamic QR — server-trusted fields), or the
    explicit recipient/amount/idempotency_key trio."""

    sender_wallet = serializers.UUIDField()
    qr_token = serializers.CharField(required=False)
    recipient_wallet = serializers.UUIDField(required=False)
    amount = serializers.IntegerField(min_value=1, required=False)
    idempotency_key = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if attrs.get("qr_token"):
            return attrs
        missing = [f for f in ("recipient_wallet", "amount", "idempotency_key")
                   if attrs.get(f) is None]
        if missing:
            raise serializers.ValidationError(
                {f: "required when qr_token is not provided" for f in missing}
            )
        return attrs


class DynamicQRSerializer(serializers.Serializer):
    wallet_id = serializers.UUIDField()
    amount = serializers.IntegerField(min_value=1)


class ScanSerializer(serializers.Serializer):
    token = serializers.CharField()
