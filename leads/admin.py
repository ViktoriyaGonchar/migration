from django.contrib import admin

from .models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "country", "source", "created_at")
    list_filter = ("created_at", "source")
    search_fields = ("name", "email", "country", "message")
