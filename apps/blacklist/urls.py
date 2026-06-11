from django.urls import path

from .views import BlockView, HistoryView, UnblockView

urlpatterns = [
    path("block/", BlockView.as_view()),
    path("<uuid:pk>/unblock/", UnblockView.as_view()),
    path("history/", HistoryView.as_view()),
]
