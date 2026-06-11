from django.contrib import admin

from .models import BlacklistEntry


@admin.register(BlacklistEntry)
class BlacklistEntryAdmin(admin.ModelAdmin):
    list_display = ("target_type", "target_value", "reason", "blocked_by",
                    "created_at", "unblocked_at")
    list_filter = ("target_type",)
    search_fields = ("target_value",)

    def has_delete_permission(self, request, obj=None):
        return False  # audit trail: rows are never deleted
