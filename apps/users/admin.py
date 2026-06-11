from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class HamyonUserAdmin(UserAdmin):
    list_display = ("username", "phone", "kyc_level", "telegram_chat_id", "is_staff")
    fieldsets = UserAdmin.fieldsets + (
        ("Hamyon", {"fields": ("phone", "telegram_chat_id", "kyc_level")}),
    )
