from django.urls import path

from .views import (
    PaymentCancelView,
    PaymentConfirmView,
    PaymentInitiateView,
    PaymentStatusView,
)

urlpatterns = [
    path("initiate/", PaymentInitiateView.as_view()),
    path("<uuid:pk>/confirm/", PaymentConfirmView.as_view()),
    path("<uuid:pk>/cancel/", PaymentCancelView.as_view()),
    path("<uuid:pk>/", PaymentStatusView.as_view()),
]
