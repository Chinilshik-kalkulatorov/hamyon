from django.urls import path

from .views import KYCApproveView, KYCRejectView, KYCStatusView, KYCSubmitView

urlpatterns = [
    path("submit/", KYCSubmitView.as_view()),
    path("status/", KYCStatusView.as_view()),
    path("admin/<uuid:pk>/approve/", KYCApproveView.as_view()),
    path("admin/<uuid:pk>/reject/", KYCRejectView.as_view()),
]
