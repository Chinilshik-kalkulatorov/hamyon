from django.urls import path

from .views import RegisterTelegramView

urlpatterns = [
    path("me/telegram/", RegisterTelegramView.as_view()),
]
