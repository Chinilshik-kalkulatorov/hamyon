from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import service
from .models import BlacklistEntry
from .serializers import BlacklistEntrySerializer, BlockSerializer, UnblockSerializer


class BlockView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = BlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = service.block(by=request.user, **serializer.validated_data)
        return Response(BlacklistEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


class UnblockView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        serializer = UnblockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = get_object_or_404(BlacklistEntry, pk=pk)
        try:
            service.unblock(entry, reason=serializer.validated_data["reason"], by=request.user)
        except ValueError:
            return Response({"code": "already_unblocked"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BlacklistEntrySerializer(entry).data)


class HistoryView(APIView):
    """Full block/unblock audit trail, optionally filtered by target."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = BlacklistEntry.objects.all()
        target_type = request.query_params.get("target_type")
        target_value = request.query_params.get("target_value")
        if target_type:
            qs = qs.filter(target_type=target_type)
        if target_value:
            qs = qs.filter(target_value=target_value)
        return Response(BlacklistEntrySerializer(qs[:200], many=True).data)
