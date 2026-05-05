from django.contrib import admin

from .models import AccessToken


@admin.register(AccessToken)
class AccessTokenAdmin(admin.ModelAdmin):
    list_display = ("token", "email", "full_name", "is_active", "expires_at", "last_used_at", "created_at")
    list_filter = ("is_active", "created_at", "expires_at")
    search_fields = ("token", "email", "full_name", "notes")
