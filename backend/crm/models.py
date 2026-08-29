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


class TaskCategory(models.Model):
    """Managed category list (reviewer's demand: dropdown, never free text).
    department="" means the category is global — offered for every
    department. Only managers/admin create categories."""
    name = models.CharField(max_length=60)
    department = models.CharField(max_length=20, choices=Department.choices,
                                  blank=True, default="")
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["department", "name"]
        constraints = [
            models.UniqueConstraint(fields=["department", "name"], name="uniq_dept_category"),
        ]
        verbose_name_plural = "task categories"

    def __str__(self):
        return f"{self.name}" + (f" ({self.get_department_display()})" if self.department else " (all)")


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
    # Department is picked first on the form; the category list filters by it
    department = models.CharField(max_length=20, choices=Department.choices,
                                  blank=True, default="")
    category = models.CharField(max_length=60, blank=True, default="")
    frequency = models.CharField(max_length=10, choices=TaskFrequency.choices, default=TaskFrequency.ONE_TIME)
    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks")
    # E1: sub-tasks — one level deep (a sub-task can't have its own children)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE,
                               related_name="subtasks")
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
    # Recurrence stops after this date (teardown: Repeat -> End Date)
    repeat_until = models.DateField(null=True, blank=True)
    # Effort value in minutes -- set by the ASSIGNER ("I know how long it takes").
    effort_minutes = models.PositiveIntegerField(null=True, blank=True)
    # The assignee's one-time counter-estimate ("Amit says 1h, Bhavna says 4h").
    # Never overwrites the assigner's value; both feed the review reports.
    assignee_estimate_minutes = models.PositiveIntegerField(null=True, blank=True)
    # P1: latest self-reported "% work done" (status updates, repeatable)
    progress_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    # P2: TOTAL effort actually spent, entered by the assignee (running total
    # via status updates, finalized at completion) -- feeds Time Spent report
    actual_minutes = models.PositiveIntegerField(null=True, blank=True)
    # Evidence captured when completing (Task Settings can make it mandatory)
    completion_note = models.CharField(max_length=500, blank=True, default="")
    # Soft delete: tasks land in the Deleted bin, recoverable by admin
    deleted_at = models.DateTimeField(null=True, blank=True)
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

    @property
    def code(self) -> str:
        return f"T-{self.pk:05d}"

    def __str__(self):
        return f"{self.code} {self.title} -> {self.assigned_to}"


class ChangeRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class TaskChangeRequest(models.Model):
    """The in-system Modification Request. Nobody (except Admin) edits a task
    directly any more -- a change is PROPOSED here and applied only on
    approval, so scores can't be quietly manipulated.

    Routing: raised by the assignee -> the task creator approves (or
    ESCALATES it to admin); raised by the creator (their own mistake) -> an
    Admin approves. Admin can always see and review everything."""
    # set via the Escalate decision: the creator hands the call to admin
    escalated = models.BooleanField(default=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="change_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                     related_name="task_change_requests")
    # e.g. {"due_at": "...", "effort_minutes": 120, "frequency": "one_time",
    #        "priority": "high", "title": "...", "cancel": true}
    changes = models.JSONField(default=dict)
    reason = models.TextField(max_length=1000)
    status = models.CharField(max_length=10, choices=ChangeRequestStatus.choices,
                              default=ChangeRequestStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="reviewed_task_changes")
    remarks = models.CharField(max_length=300, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"])]

    # Raw keys like "due_at"/"assigned_to" are meaningless in an email, and a
    # bare user id ("assignee -> 48") is worse. One renderer, used by both the
    # notification and the Requests card, so they can never drift apart.
    FIELD_LABELS = {
        "due_at": "Due date", "effort_minutes": "Effort", "priority": "Priority",
        "title": "Title", "description": "Description", "frequency": "Recurrence",
        "repeat_until": "Repeat until", "category": "Category",
        "assigned_to": "Assignee",
    }

    @staticmethod
    def _fmt(field, value):
        if value in (None, ""):
            return "not set"
        if field == "due_at":
            dt = value
            if isinstance(dt, str):
                from django.utils.dateparse import parse_datetime
                dt = parse_datetime(dt) or value
            if hasattr(dt, "date"):
                return f"{timezone.localtime(dt):%d %b %Y, %I:%M %p}"
            return str(value)
        if field == "effort_minutes":
            m = int(value)
            if m < 60:
                return f"{m}m"
            return f"{m // 60}h" if m % 60 == 0 else f"{m // 60}h {m % 60}m"
        if field == "assigned_to":
            from accounts.models import User
            who = value if hasattr(value, "pk") else User.objects.filter(pk=value).first()
            return (who.get_full_name() or who.username) if who else f"user #{value}"
        if field == "priority":
            return dict(LeadPriority.choices).get(value, value)
        if field == "frequency":
            return dict(TaskFrequency.choices).get(value, value)
        text = str(value)
        return text if len(text) <= 200 else text[:199].rstrip() + "…"

    def describe(self) -> list[str]:
        """Human-readable lines for every proposed change. While the request
        is pending the task still holds the old value, so show 'old -> new';
        once reviewed the change is already applied and an 'X -> X' arrow
        would just read as a bug, so show the requested value alone."""
        pending = self.status == ChangeRequestStatus.PENDING
        lines = []
        for field, new in (self.changes or {}).items():
            if field == "cancel":
                lines.append("Cancel the task")
                continue
            label = self.FIELD_LABELS.get(field, field)
            shown_new = self._fmt(field, new)
            old = self._fmt(field, getattr(self.task, field, None)) if pending else None
            lines.append(f"{label}: {old} -> {shown_new}"
                         if pending and old != shown_new else f"{label}: {shown_new}")
        return lines

    def __str__(self):
        return f"Change request on {self.task_id} by {self.requested_by} [{self.status}]"


def task_attachment_path(instance, filename):
    return f"task_files/{instance.task_id}/{filename}"


class TaskAttachment(models.Model):
    """Files on a task -- including the proof-of-work demanded by Task
    Settings when completing ("keeps ticking it daily" fix)."""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=task_attachment_path)
    filename = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TaskSettings(models.Model):
    """Org-wide task policies (singleton row, pk=1). The completion-evidence
    switches mirror the reference app's 'Set Mandatory Fields'."""
    require_completion_remarks = models.BooleanField(default=False)
    require_completion_attachment = models.BooleanField(default=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    class Meta:
        verbose_name_plural = "task settings"


class TaskActivity(models.Model):
    """Audit trail for tasks -- who did what, when (the 'Activities' feed).
    kind='comment' rows are human conversation; kind='log' rows are system."""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    text = models.CharField(max_length=300)
    kind = models.CharField(max_length=10, default="log",
                            choices=[("log", "Log"), ("comment", "Comment")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "task activities"


class TaskChecklistItem(models.Model):
    """E1: tickable sub-items inside one task ('the small steps')."""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="checklist")
    text = models.CharField(max_length=200)
    done = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)

    class Meta:
        ordering = ["order", "id"]


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
