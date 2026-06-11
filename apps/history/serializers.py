from rest_framework import serializers

from apps.core.models import LedgerEntry


class LedgerEntrySerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()

    class Meta:
        model = LedgerEntry
        fields = ["id", "wallet", "type", "amount", "ref_id", "related_entry",
                  "status", "created_at"]

    def get_status(self, obj):
        """Holds are 'pending' until released by a reversal; everything else
        is 'posted'. Derived — ledger rows themselves never change."""
        if obj.type != LedgerEntry.Type.HOLD:
            return "posted"
        released = getattr(obj, "is_released", None)
        if released is None:
            released = obj.reversals.exists()
        return "released" if released else "pending"
