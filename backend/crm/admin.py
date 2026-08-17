from django.contrib import admin

from .models import Lead, LeadDocument, LeadEvent, Quotation


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("customer_name", "company", "status", "priority", "department", "assigned_to", "follow_up_at")
    list_filter = ("status", "priority", "department", "source")
    search_fields = ("customer_name", "company", "phone", "email")


admin.site.register(LeadEvent)
admin.site.register(LeadDocument)
admin.site.register(Quotation)
