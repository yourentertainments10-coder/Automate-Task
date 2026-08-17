from django.contrib import admin

from .models import Form, FormField, FormSubmission, SubmissionFile


class FormFieldInline(admin.TabularInline):
    model = FormField
    extra = 0


@admin.register(Form)
class FormAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "created_by", "create_lead", "create_task", "created_at")
    list_filter = ("status", "create_lead", "create_task")
    inlines = [FormFieldInline]


@admin.register(FormSubmission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("form", "person", "lead", "task", "created_at")


admin.site.register(SubmissionFile)
