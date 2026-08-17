from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CrmUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "department", "is_active")
    list_filter = ("role", "department", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("CRM", {"fields": ("role", "department", "whatsapp_phone")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("CRM", {"fields": ("role", "department", "whatsapp_phone")}),
    )
