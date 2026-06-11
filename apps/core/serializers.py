from rest_framework import serializers

from .models import Wallet


def format_uzs(tiyin: int) -> str:
    whole, frac = divmod(abs(tiyin), 100)
    sign = "-" if tiyin < 0 else ""
    if frac:
        return f"{sign}{whole:,}.{frac:02d}"
    return f"{sign}{whole:,}"


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ["id", "currency", "static_qr_url", "created_at"]


class BalanceSerializer(serializers.Serializer):
    """Read-only view over the derived balance. Amounts in tiyin."""

    balance = serializers.IntegerField()
    held = serializers.IntegerField()
    available = serializers.IntegerField()
    balance_uzs = serializers.SerializerMethodField()
    available_uzs = serializers.SerializerMethodField()

    def get_balance_uzs(self, obj):
        return format_uzs(obj["balance"])

    def get_available_uzs(self, obj):
        return format_uzs(obj["available"])
