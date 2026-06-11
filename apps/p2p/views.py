from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import map_domain_errors
from apps.core.models import Wallet
from apps.payments.serializers import OTPCodeSerializer

from . import qr, services
from .models import TransferRequest
from .serializers import (
    DynamicQRSerializer,
    ScanSerializer,
    TransferInitiateSerializer,
    TransferRequestSerializer,
)


def _qr_error_response(exc):
    if isinstance(exc, qr.QRAlreadyUsedError):
        return Response({"code": "qr_already_used"}, status=status.HTTP_409_CONFLICT)
    return Response({"code": "qr_invalid", "detail": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST)


class TransferInitiateView(APIView):
    @map_domain_errors
    def post(self, request):
        serializer = TransferInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.get("qr_token"):
            # Server-side decode: the client cannot tamper with amount/recipient.
            try:
                intent = qr.decode_dynamic_qr(data["qr_token"])
            except qr.QRError as exc:
                return _qr_error_response(exc)
            recipient_wallet = intent["recipient_wallet"]
            amount = intent["amount"]
            idempotency_key = intent["ref_id"]  # makes the QR single-use
        else:
            recipient_wallet = data["recipient_wallet"]
            amount = data["amount"]
            idempotency_key = data["idempotency_key"]

        try:
            transfer_request, created = services.initiate_transfer(
                user=request.user,
                sender_wallet_id=data["sender_wallet"],
                recipient_wallet_id=recipient_wallet,
                amount=amount,
                idempotency_key=idempotency_key,
            )
        except Wallet.DoesNotExist:
            raise Http404
        return Response(
            TransferRequestSerializer(transfer_request).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class TransferConfirmView(APIView):
    @map_domain_errors
    def post(self, request, pk):
        serializer = OTPCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        get_object_or_404(TransferRequest, pk=pk, sender_wallet__user=request.user)
        transfer_request = services.confirm_transfer(
            request.user, pk, serializer.validated_data["code"]
        )
        return Response(TransferRequestSerializer(transfer_request).data)


class TransferStatusView(APIView):
    def get(self, request, pk):
        transfer_request = get_object_or_404(
            TransferRequest, pk=pk, sender_wallet__user=request.user
        )
        return Response(TransferRequestSerializer(transfer_request).data)


class StaticQRView(APIView):
    """PNG with the wallet's permanent receive QR. Scanning it pre-fills the
    recipient; the sender enters the amount manually."""

    def get(self, request, wallet_id):
        wallet = get_object_or_404(Wallet, id=wallet_id, user=request.user)
        if not wallet.static_qr_url:
            wallet.static_qr_url = request.build_absolute_uri()
            wallet.save(update_fields=["static_qr_url"])
        png = qr.qr_png_bytes(qr.static_qr_payload(wallet.id))
        return HttpResponse(png, content_type="image/png")


class DynamicQRView(APIView):
    """Issue a signed, single-use, 15-minute payment QR for my wallet."""

    def post(self, request):
        serializer = DynamicQRSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wallet = get_object_or_404(
            Wallet, id=serializer.validated_data["wallet_id"], user=request.user
        )
        return Response(qr.issue_dynamic_qr(wallet, serializer.validated_data["amount"]))


class ScanView(APIView):
    """Decode + verify a dynamic QR and return the pre-filled TransferIntent."""

    def post(self, request):
        serializer = ScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            intent = qr.decode_dynamic_qr(serializer.validated_data["token"])
        except qr.QRError as exc:
            return _qr_error_response(exc)
        if not Wallet.objects.filter(id=intent["recipient_wallet"]).exists():
            raise Http404
        return Response({"transfer_intent": intent})
