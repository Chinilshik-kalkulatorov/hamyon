from django.urls import path

from .views import (
    AnalyticsView,
    HistoryDetailView,
    HistoryExportView,
    HistoryListView,
)

urlpatterns = [
    path("wallet/<uuid:wallet_id>/history/", HistoryListView.as_view()),
    path("wallet/<uuid:wallet_id>/history/export/", HistoryExportView.as_view()),
    path("wallet/<uuid:wallet_id>/analytics/", AnalyticsView.as_view()),
    path("history/<uuid:pk>/", HistoryDetailView.as_view()),
]
