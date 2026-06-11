from django.urls import path

from apps.p2p.views import StaticQRView

from .views import WalletBalanceView, WalletListCreateView

urlpatterns = [
    path("wallet/", WalletListCreateView.as_view()),
    path("wallet/<uuid:wallet_id>/balance/", WalletBalanceView.as_view()),
    path("wallet/<uuid:wallet_id>/qr/static/", StaticQRView.as_view()),
]
