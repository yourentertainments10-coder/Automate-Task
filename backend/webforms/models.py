"""Form builder: forms, their fields, and submissions.

A published form can be filled by signed-in employees in-app AND by
customers via an unauthenticated share link (/api/public/forms/<token>/).
Submissions can auto-create a Lead (which reuses the existing
auto-assignment engine) and/or a follow-up Task.
"""
import secrets

from django.conf import settings
from django.db import models

from accounts.models import Department


def new_token():
    return secrets.token_urlsafe(16)


class FormStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    CLOSED = "closed", "Closed"


class Form(models.Model):
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=FormStatus.choices, default=FormStatus.DRAFT)
    public_token = models.CharField(max_length=40, unique=True, default=new_token)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                   related_name="forms")
    # --- integrations -------------------------------------------------
    create_lead = models.BooleanField(default=False)
    lead_department = models.CharField(max_length=20, choices=Department.choices,
                                       default=Department.SALES)
    create_task = models.BooleanField(default=False)
    task_title = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} [{self.status}]"


class FieldType(models.TextChoices):
    SHORT_TEXT = "short_text", "Short text"
    LONG_TEXT = "long_text", "Long text"
    NUMBER = "number", "Number"
    EMAIL = "email", "Email"
    PHONE = "phone", "Phone"
    DATE = "date", "Date"
    DROPDOWN = "dropdown", "Dropdown"
    RADIO = "radio", "Radio"
    CHECKBOX = "checkbox", "Checkbox"
    FILE = "file", "File upload"


class LeadAttr(models.TextChoices):
    NONE = "", "—"
    CUSTOMER_NAME = "customer_name", "Customer name"
    PHONE = "phone", "Phone"
    EMAIL = "email", "Email"
    COMPANY = "company", "Company"
    REQUIREMENT = "requirement", "Requirement"


class FormField(models.Model):
    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="fields")
    label = models.CharField(max_length=200)
    type = models.CharField(max_length=12, choices=FieldType.choices, default=FieldType.SHORT_TEXT)
    required = models.BooleanField(default=False)
    options = models.JSONField(default=list, blank=True)  # dropdown/radio/checkbox choices
    # Which Lead attribute this answer fills when create_lead is on
    lead_attr = models.CharField(max_length=20, choices=LeadAttr.choices, blank=True, default="")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.label} ({self.type})"


class FormSubmission(models.Model):
    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="submissions")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL)
    answers = models.JSONField(default=dict)  # {field_id(str): value}
    lead = models.ForeignKey("crm.Lead", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="form_submissions")
    task = models.ForeignKey("crm.Task", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def person(self) -> str:
        if self.submitted_by:
            return self.submitted_by.get_full_name() or self.submitted_by.username
        for f in self.form.fields.all():
            if f.lead_attr == LeadAttr.CUSTOMER_NAME:
                v = self.answers.get(str(f.id))
                if v:
                    return str(v)
        return "Anonymous"


def submission_file_path(instance, filename):
    return f"form_uploads/{instance.submission.form_id}/{instance.submission_id}/{filename}"


class SubmissionFile(models.Model):
    submission = models.ForeignKey(FormSubmission, on_delete=models.CASCADE, related_name="files")
    field_id = models.PositiveIntegerField()
    file = models.FileField(upload_to=submission_file_path)
    filename = models.CharField(max_length=255)
