from django.contrib import admin

from apps.core.exceptions import InvalidTransition

from .models import KYCApplication


@admin.register(KYCApplication)
class KYCApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "requested_level", "status", "reviewed_by", "created_at")
    list_filter = ("status", "requested_level")
    actions = ["approve_selected", "reject_selected"]
    readonly_fields = ("status", "reviewed_by", "reviewed_at")

    @admin.action(description="Approve selected applications")
    def approve_selected(self, request, queryset):
        for app in queryset:
            try:
                app.approve(by=request.user)
            except InvalidTransition:
                self.message_user(request, f"{app} is not pending, skipped")

    @admin.action(description="Reject selected applications")
    def reject_selected(self, request, queryset):
        for app in queryset:
            try:
                app.reject(by=request.user, reason="Rejected via admin action")
            except InvalidTransition:
                self.message_user(request, f"{app} is not pending, skipped")
