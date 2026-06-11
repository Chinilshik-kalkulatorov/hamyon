from rest_framework import serializers

from .models import PaymentRequest


class PaymentRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentRequest
        fields = ["id", "wallet", "direction", "amount", "status",
                  "idempotency_key", "expires_at", "created_at"]


class PaymentInitiateSerializer(serializers.Serializer):
    wallet_id = serializers.UUIDField()
    direction = serializers.ChoiceField(choices=PaymentRequest.Direction.choices)
    amount = serializers.IntegerField(min_value=1, help_text="Tiyin")
    idempotency_key = serializers.UUIDField()


class OTPCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=6, trim_whitespace=True)
