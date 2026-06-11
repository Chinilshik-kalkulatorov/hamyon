from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Wallet
from .serializers import BalanceSerializer, WalletSerializer
from .services.balance import get_wallet_balance


def get_own_wallet_or_404(request, wallet_id) -> Wallet:
    # Filtering by user means strangers get 404, not 403: existence not leaked.
    return get_object_or_404(Wallet, id=wallet_id, user=request.user)


class WalletListCreateView(APIView):
    def get(self, request):
        wallets = request.user.wallets.all().order_by("created_at")
        return Response(WalletSerializer(wallets, many=True).data)

    def post(self, request):
        wallet = Wallet.objects.create(user=request.user)
        return Response(WalletSerializer(wallet).data, status=status.HTTP_201_CREATED)


class WalletBalanceView(APIView):
    """GET /api/wallet/{id}/balance/ — read-only, never modifies any record."""

    def get(self, request, wallet_id):
        wallet = get_own_wallet_or_404(request, wallet_id)
        data = get_wallet_balance(wallet.id)
        return Response(BalanceSerializer(data).data)
