from django.contrib import admin

from .models import LedgerEntry, Transfer, Wallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "currency", "created_at", "balance_display")
    readonly_fields = ("id", "created_at")

    @admin.display(description="Balance (derived)")
    def balance_display(self, obj):
        info = obj.balance_info
        return f"{info['balance']} tiyin (available {info['available']})"


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    """View-only: the ledger is append-only even for admins."""

    list_display = ("id", "wallet", "type", "amount", "ref_id", "created_at")
    list_filter = ("type",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ("id", "sender_wallet", "recipient_wallet", "amount", "created_at")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
