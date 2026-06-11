from django.contrib import admin

from .models import TransferRequest


@admin.register(TransferRequest)
class TransferRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "sender_wallet", "recipient_wallet", "amount", "status",
                    "created_at")
    list_filter = ("status",)
    readonly_fields = ("status", "transfer", "idempotency_key")
