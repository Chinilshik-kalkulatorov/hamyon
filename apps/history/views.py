from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import LedgerEntry, Wallet
from apps.core.services.analytics import get_wallet_analytics

from .pagination import DEFAULT_PAGE_SIZE, InvalidCursor, paginate
from .serializers import LedgerEntrySerializer
from .tasks import export_wallet_history


def _annotated_entries(wallet_id):
    from django.db.models import Exists, OuterRef

    released = LedgerEntry.objects.filter(
        related_entry=OuterRef("pk"), type=LedgerEntry.Type.REVERSAL
    )
    return LedgerEntry.objects.filter(wallet_id=wallet_id).annotate(
        is_released=Exists(released)
    )


def _apply_filters(queryset, params):
    entry_type = params.get("type")
    if entry_type:
        queryset = queryset.filter(type=entry_type)

    date_from = params.get("from")
    if date_from and (parsed := parse_datetime(date_from)):
        queryset = queryset.filter(created_at__gte=parsed)
    date_to = params.get("to")
    if date_to and (parsed := parse_datetime(date_to)):
        queryset = queryset.filter(created_at__lte=parsed)

    status_param = params.get("status")
    if status_param == "pending":
        queryset = queryset.filter(type=LedgerEntry.Type.HOLD, is_released=False)
    elif status_param == "released":
        queryset = queryset.filter(type=LedgerEntry.Type.HOLD, is_released=True)
    elif status_param == "posted":
        queryset = queryset.exclude(type=LedgerEntry.Type.HOLD)
    return queryset


class HistoryListView(APIView):
    """GET /api/wallet/{id}/history/?cursor=&type=&status=&from=&to=

    Cursor pagination only. A user sees entries of their own wallets only.
    """

    def get(self, request, wallet_id):
        get_object_or_404(Wallet, id=wallet_id, user=request.user)
        queryset = _apply_filters(_annotated_entries(wallet_id), request.query_params)
        try:
            page_size = int(request.query_params.get("page_size", DEFAULT_PAGE_SIZE))
            page = paginate(queryset, request.query_params.get("cursor"), page_size)
        except (InvalidCursor, ValueError):
            return Response({"code": "invalid_cursor"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "results": LedgerEntrySerializer(page.items, many=True).data,
            "next_cursor": page.next_cursor,
        })


class HistoryDetailView(APIView):
    def get(self, request, pk):
        entry = get_object_or_404(
            LedgerEntry.objects.select_related("wallet"), pk=pk, wallet__user=request.user
        )
        return Response(LedgerEntrySerializer(entry).data)


class AnalyticsView(APIView):
    """GET /api/wallet/{id}/analytics/?days=30 — spend summary for the owner."""

    def get(self, request, wallet_id):
        get_object_or_404(Wallet, id=wallet_id, user=request.user)
        days = request.query_params.get("days", 30)
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 30
        return Response(get_wallet_analytics(wallet_id, days))


class HistoryExportView(APIView):
    """POST → Celery writes the CSV and sends a download link via Telegram."""

    def post(self, request, wallet_id):
        get_object_or_404(Wallet, id=wallet_id, user=request.user)
        export_wallet_history.delay(str(wallet_id), request.user.pk)
        return Response({"status": "export_started"}, status=status.HTTP_202_ACCEPTED)
