from django.urls import path

from .views import (
    DynamicQRView,
    ScanView,
    TransferConfirmView,
    TransferInitiateView,
    TransferStatusView,
)

urlpatterns = [
    path("transfer/", TransferInitiateView.as_view()),
    path("transfers/<uuid:pk>/confirm/", TransferConfirmView.as_view()),
    path("transfers/<uuid:pk>/", TransferStatusView.as_view()),
    path("qr/dynamic/", DynamicQRView.as_view()),
    path("scan/", ScanView.as_view()),
]
