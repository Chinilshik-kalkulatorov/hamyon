from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import map_domain_errors
from apps.kyc.services import get_spending_limit

from .models import KYCApplication
from .serializers import KYCApplicationSerializer, KYCSubmitSerializer


class KYCSubmitView(APIView):
    """POST /api/kyc/submit/ — file references only, never the files."""

    def post(self, request):
        serializer = KYCSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if request.user.kyc_applications.filter(
            status=KYCApplication.Status.PENDING
        ).exists():
            return Response(
                {"code": "kyc_already_pending"}, status=status.HTTP_400_BAD_REQUEST
            )
        app = KYCApplication.objects.create(user=request.user, **serializer.validated_data)
        return Response(KYCApplicationSerializer(app).data, status=status.HTTP_201_CREATED)


class KYCStatusView(APIView):
    """GET /api/kyc/status/ — current level, limit and latest application."""

    def get(self, request):
        latest = request.user.kyc_applications.first()  # Meta.ordering = -created_at
        return Response({
            "level": request.user.kyc_level,
            "spending_limit_30d": get_spending_limit(request.user),
            "latest_application": KYCApplicationSerializer(latest).data if latest else None,
        })


class KYCApproveView(APIView):
    permission_classes = [IsAdminUser]

    @map_domain_errors
    def post(self, request, pk):
        app = get_object_or_404(KYCApplication, pk=pk)
        app.approve(by=request.user)
        return Response(KYCApplicationSerializer(app).data)


class KYCRejectView(APIView):
    permission_classes = [IsAdminUser]

    @map_domain_errors
    def post(self, request, pk):
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"code": "reason_required"}, status=status.HTTP_400_BAD_REQUEST)
        app = get_object_or_404(KYCApplication, pk=pk)
        app.reject(by=request.user, reason=reason)
        return Response(KYCApplicationSerializer(app).data)
