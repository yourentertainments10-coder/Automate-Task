from django.contrib import admin

from .models import DirectoryTemplate, Industry


@admin.register(Industry)
class IndustryAdmin(admin.ModelAdmin):
    list_display = ("name", "icon", "order", "active")


@admin.register(DirectoryTemplate)
class DirectoryTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "industry", "category", "priority", "frequency", "step_count", "active")
    list_filter = ("industry", "category", "priority", "active")
    search_fields = ("name", "description", "category")
