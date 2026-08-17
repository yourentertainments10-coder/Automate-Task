from django.contrib import admin

from .models import InboundMessage


@admin.register(InboundMessage)
class InboundMessageAdmin(admin.ModelAdmin):
    list_display = ("channel", "sender", "sender_name", "status", "lead", "created_at")
    list_filter = ("channel", "status")
    search_fields = ("sender", "sender_name", "body")
