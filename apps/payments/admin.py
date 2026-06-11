from django.contrib import admin

from .models import PaymentRequest


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "wallet", "direction", "amount", "status", "created_at")
    list_filter = ("direction", "status")
    readonly_fields = ("status", "hold_entry", "result_entry", "idempotency_key")
