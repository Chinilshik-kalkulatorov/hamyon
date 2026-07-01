from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.api import map_domain_errors
from apps.core.models import Wallet

from . import services
from .models import PaymentRequest
from .serializers import (
    OTPCodeSerializer,
    PaymentInitiateSerializer,
    PaymentRequestSerializer,
)


class PaymentInitiateView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payment"

    @map_domain_errors
    def post(self, request):
        serializer = PaymentInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not Wallet.objects.filter(id=data["wallet_id"], user=request.user).exists():
            raise Http404

        payment, created = services.initiate_payment(
            user=request.user,
            wallet_id=data["wallet_id"],
            direction=data["direction"],
            amount=data["amount"],
            idempotency_key=data["idempotency_key"],
        )
        return Response(
            PaymentRequestSerializer(payment).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PaymentConfirmView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payment"

    @map_domain_errors
    def post(self, request, pk):
        serializer = OTPCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        get_object_or_404(PaymentRequest, pk=pk, wallet__user=request.user)
        payment = services.confirm_payment(request.user, pk, serializer.validated_data["code"])
        return Response(PaymentRequestSerializer(payment).data)


class PaymentCancelView(APIView):
    @map_domain_errors
    def post(self, request, pk):
        get_object_or_404(PaymentRequest, pk=pk, wallet__user=request.user)
        payment = services.cancel_payment(request.user, pk)
        return Response(PaymentRequestSerializer(payment).data)


class PaymentStatusView(APIView):
    def get(self, request, pk):
        payment = get_object_or_404(PaymentRequest, pk=pk, wallet__user=request.user)
        return Response(PaymentRequestSerializer(payment).data)
