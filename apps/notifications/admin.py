from django.contrib import admin

from .models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "channel", "status", "text")
    list_filter = ("status", "channel")

    def has_change_permission(self, request, obj=None):
        return False
