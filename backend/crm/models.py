"""CRM core: leads, their timeline, documents and quotations.

Every meaningful change to a lead lands in LeadEvent -- that table IS the
"communication history" requirement, and later phases (WhatsApp/Gmail/AI)
append to it with their own event types instead of inventing new tables.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import Department


class LeadStatus(models.TextChoices):
    NEW = "new", "New"
    CONTACTED = "contacted", "Contacted"
    QUOTATION_SENT = "quotation_sent", "Quotation Sent"
    NEGOTIATION = "negotiation", "Negotiation"
    WON = "won", "Won"
    LOST = "lost", "Lost"


OPEN_STATUSES = [LeadStatus.NEW, LeadStatus.CONTACTED, LeadStatus.QUOTATION_SENT, LeadStatus.NEGOTIATION]


class LeadSource(models.TextChoices):
    MANUAL = "manual", "Manual"
    WHATSAPP = "whatsapp", "WhatsApp"
    GMAIL = "gmail", "Gmail"
    WEB = "web", "Website"
    INDIAMART = "indiamart", "IndiaMART"
    TRADEINDIA = "tradeindia", "TradeIndia"
    OTHER = "other", "Other"


class LeadPriority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class Lead(models.Model):
    customer_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    company = models.CharField(max_length=200, blank=True, default="")
    requirement = models.TextField(blank=True, default="")

    source = models.CharField(max_length=20, choices=LeadSource.choices, default=LeadSource.MANUAL)
    department = models.CharField(max_length=20, choices=Department.choices, default=Department.SALES)
    status = models.CharField(max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW)
    priority = models.CharField(max_length=10, choices=LeadPriority.choices, default=LeadPriority.NORMAL)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leads",
    )
    follow_up_at = models.DateTimeField(null=True, blank=True)
    # When we last sent a follow-up-due notification for the CURRENT follow_up_at
    reminded_at = models.DateTimeField(null=True, blank=True)
    estimated_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Filled by the AI intake in Phase 3 (intent, extracted items, confidence...)
    ai_meta = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_leads",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["department", "status"]),
            models.Index(fields=["follow_up_at"]),
        ]

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def is_overdue(self) -> bool:
        return bool(self.is_open and self.follow_up_at and self.follow_up_at < timezone.now())

    def __str__(self):
        return f"{self.customer_name} [{self.get_status_display()}]"


class AssignmentRule(models.Model):
    """One auto-assignment rule per department. member_ids is an ORDERED
    list of user PKs -- round-robin walks it in order; `fixed` always uses
    the first available member."""

    class Strategy(models.TextChoices):
        ROUND_ROBIN = "round_robin", "Round robin"
        FIXED = "fixed", "Fixed"

    department = models.CharField(max_length=20, choices=Department.choices, unique=True)
    strategy = models.CharField(max_length=20, choices=Strategy.choices, default=Strategy.ROUND_ROBIN)
    member_ids = models.JSONField(default=list, blank=True)
    rr_index = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_department_display()} ({self.get_strategy_display()})"


class EventType(models.TextChoices):
    CREATED = "created", "Created"
    NOTE = "note", "Note"
    STATUS_CHANGE = "status_change", "Status change"
    ASSIGNMENT = "assignment", "Assignment"
    FOLLOW_UP = "follow_up", "Follow-up set"
    DOCUMENT = "document", "Document"
    QUOTATION = "quotation", "Quotation"
    CALL = "call", "Call"
    EMAIL_IN = "email_in", "Email received"
    EMAIL_OUT = "email_out", "Email sent"
    WA_IN = "wa_in", "WhatsApp received"
    WA_OUT = "wa_out", "WhatsApp sent"


class LeadEvent(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=20, choices=EventType.choices)
    body = models.TextField(blank=True, default="")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TaskStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In Progress"
    DONE = "done", "Done"


class TaskFrequency(models.TextChoices):
    ONE_TIME = "one_time", "One time"
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"


class Task(models.Model):
    """A unit of work for an employee, optionally linked to a lead. Task
    completion on a linked lead lands in that lead's timeline. Completing a
    recurring task auto-creates the next occurrence."""
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=60, blank=True, default="")
    frequency = models.CharField(max_length=10, choices=TaskFrequency.choices, default=TaskFrequency.ONE_TIME)
    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks")
    # Optional workspace-group scoping: group members can see the group's tasks.
    group = models.ForeignKey("workspace.Group", null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="tasks")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tasks")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="created_tasks")
    subscribers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="subscribed_tasks")
    status = models.CharField(max_length=15, choices=TaskStatus.choices, default=TaskStatus.OPEN)
    priority = models.CharField(max_length=10, choices=LeadPriority.choices, default=LeadPriority.NORMAL)
    due_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["due_at"]),
        ]

    @property
    def is_overdue(self) -> bool:
        return bool(self.status != TaskStatus.DONE and self.due_at and self.due_at < timezone.now())

    def __str__(self):
        return f"{self.title} -> {self.assigned_to}"


class TaskActivity(models.Model):
    """Audit trail for tasks -- who did what, when (the 'Activities' feed)."""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    text = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "task activities"


class TaskTemplate(models.Model):
    """Reusable task blueprint (the reference product's Task Templates)."""
    name = models.CharField(max_length=120, unique=True)
    category = models.CharField(max_length=60, blank=True, default="")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    priority = models.CharField(max_length=10, choices=LeadPriority.choices, default=LeadPriority.NORMAL)
    frequency = models.CharField(max_length=10, choices=TaskFrequency.choices, default=TaskFrequency.ONE_TIME)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class Holiday(models.Model):
    name = models.CharField(max_length=120)
    date = models.DateField(unique=True)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.name} ({self.date})"


def lead_doc_path(instance, filename):
    return f"lead_docs/{instance.lead_id}/{filename}"


class LeadDocument(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="documents")
    file = models.FileField(upload_to=lead_doc_path)
    filename = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class QuotationStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SENT = "sent", "Sent"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"


class Quotation(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="quotations")
    number = models.CharField(max_length=30, unique=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=QuotationStatus.choices, default=QuotationStatus.DRAFT)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating and not self.number:
            # Deterministic, unique, human-friendly: QT-<year>-<pk padded>
            self.number = f"QT-{timezone.now().year}-{self.pk:04d}"
            super().save(update_fields=["number"])
