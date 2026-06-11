from rest_framework import serializers

from apps.users.models import KYCLevel

from .models import KYCApplication


class KYCApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCApplication
        fields = [
            "id", "requested_level", "passport_ref", "selfie_ref",
            "status", "reject_reason", "created_at",
        ]
        read_only_fields = ["id", "status", "reject_reason", "created_at"]


class KYCSubmitSerializer(serializers.Serializer):
    requested_level = serializers.ChoiceField(
        choices=[KYCLevel.BASIC, KYCLevel.FULL], default=KYCLevel.BASIC
    )
    passport_ref = serializers.CharField(max_length=255)
    selfie_ref = serializers.CharField(max_length=255)
