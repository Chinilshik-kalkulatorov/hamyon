from rest_framework import serializers

from .models import BlacklistEntry


class BlacklistEntrySerializer(serializers.ModelSerializer):
    blocked_by = serializers.StringRelatedField()
    unblocked_by = serializers.StringRelatedField()

    class Meta:
        model = BlacklistEntry
        fields = [
            "id", "target_type", "target_value", "reason", "blocked_by",
            "created_at", "unblocked_at", "unblocked_by", "unblock_reason",
        ]


class BlockSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(choices=BlacklistEntry.TargetType.choices)
    target_value = serializers.CharField(max_length=64)
    reason = serializers.CharField()


class UnblockSerializer(serializers.Serializer):
    reason = serializers.CharField()
