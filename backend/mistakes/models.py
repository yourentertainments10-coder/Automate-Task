"""Mistake / Error Register with three-level accountability (Sir's spec,
20 Aug): employee owns the mistake -> manager owns the correction ->
dept head owns repeats -> founder sees only serious escalations.

The system records, reminds and escalates. It NEVER punishes on its own —
every disciplinary action needs a human decision (level3_action is a
recorded human choice, not an automated one).
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import Department


class Severity(models.TextChoices):
    LOW = "low", "Low"                    # negligible impact
    MEDIUM = "medium", "Medium"           # rework / delay / internal impact
    HIGH = "high", "High"                 # significant financial/customer impact
    CRITICAL = "critical", "Critical"     # major loss, compliance, fraud risk


class Classification(models.TextChoices):
    """Who/what actually failed — never auto-blame the employee."""
    HUMAN = "human", "Human Mistake"
    PROCESS = "process", "Process/SOP Failure"
    SYSTEM = "system", "Software/System Failure"
    MANAGEMENT = "management", "Management/Training Failure"
    EXTERNAL = "external", "External Failure"


class RootCause(models.TextChoices):
    LACK_OF_TRAINING = "lack_of_training", "Lack of training"
    LACK_OF_ATTENTION = "lack_of_attention", "Lack of attention"
    SOP_NOT_FOLLOWED = "sop_not_followed", "SOP not followed"
    SOP_MISSING = "sop_missing", "SOP missing"
    SOP_UNCLEAR = "sop_unclear", "SOP unclear"
    WRONG_INFORMATION = "wrong_information", "Wrong information provided"
    COMMUNICATION = "communication_failure", "Communication failure"
    SYSTEM_ISSUE = "system_issue", "System issue"
    DATA_ISSUE = "data_issue", "Data issue"
    WORKLOAD = "workload_issue", "Workload issue"
    TIME_PRESSURE = "time_pressure", "Time pressure"
    APPROVAL_FAILURE = "approval_failure", "Approval failure"
    HUMAN_ERROR = "human_error", "Human error"
    MANAGERIAL_FAILURE = "managerial_failure", "Managerial failure"
    VENDOR_ISSUE = "vendor_issue", "Vendor issue"
    CUSTOMER_ISSUE = "customer_issue", "Customer issue"
    OTHER = "other", "Other"


class MistakeStatus(models.TextChoices):
    OPEN = "open", "Open"                       # logged, waiting for employee
    EXPLAINED = "explained", "Explained"        # employee responded, manager to act
    RESOLVED = "resolved", "Resolved"           # manager closed it with a decision


class Level3Action(models.TextChoices):
    COACHING = "coaching", "Coaching"
    RETRAINING = "retraining", "Retraining"
    WRITTEN_WARNING = "written_warning", "Written warning"
    PIP = "pip", "Performance Improvement Plan"
    ROLE_REASSIGNMENT = "role_reassignment", "Role reassignment"
    ADDITIONAL_APPROVAL = "additional_approval", "Additional approval requirement"
    PROCESS_CHANGE = "process_change", "Process change"
    PERMISSION_SUSPENSION = "permission_suspension", "Suspension of certain permissions"
    OTHER = "other", "Other HR-approved action"


class MistakeCategory(models.Model):
    """Configurable list — admins add/edit; seeded with Sir's 29."""
    name = models.CharField(max_length=80)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["name"], name="uniq_mistake_category")]
        verbose_name_plural = "mistake categories"

    def __str__(self):
        return self.name


class MistakeSettings(models.Model):
    """Configurable SLA hours per severity (singleton, pk=1)."""
    sla_low_hours = models.PositiveIntegerField(default=72)
    sla_medium_hours = models.PositiveIntegerField(default=48)
    sla_high_hours = models.PositiveIntegerField(default=24)
    sla_critical_hours = models.PositiveIntegerField(default=4)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def hours_for(self, severity: str) -> int:
        return {
            Severity.LOW: self.sla_low_hours,
            Severity.MEDIUM: self.sla_medium_hours,
            Severity.HIGH: self.sla_high_hours,
            Severity.CRITICAL: self.sla_critical_hours,
        }.get(severity, self.sla_medium_hours)


class Mistake(models.Model):
    # who + where
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="mistakes")
    department = models.CharField(max_length=20, choices=Department.choices, blank=True)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="accountable_mistakes",
                                help_text="Accountable for the correction (reporting manager at log time).")
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="reported_mistakes")

    # what happened
    category = models.CharField(max_length=80)            # validated against MistakeCategory
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    classification = models.CharField(max_length=12, choices=Classification.choices, blank=True)
    description = models.TextField(max_length=3000)
    impact = models.CharField(max_length=500, blank=True, default="")
    financial_loss = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    task = models.ForeignKey("crm.Task", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="mistakes_here", help_text="The task where it happened.")
    lead = models.ForeignKey("crm.Lead", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="mistakes")

    # three-level accountability
    occurrence_level = models.PositiveSmallIntegerField(default=1)   # 1/2/3
    repeat_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="repeats")

    # employee's side
    explanation = models.TextField(max_length=2000, blank=True, default="")
    root_cause = models.CharField(max_length=25, choices=RootCause.choices, blank=True)
    root_cause_note = models.CharField(max_length=500, blank=True, default="")
    corrective_action = models.TextField(max_length=1000, blank=True, default="")
    preventive_action = models.TextField(max_length=1000, blank=True, default="")

    # SOP linking — "SOP followed = NO" -> employee side;
    # "SOP adequate = NO" -> the PROCESS is broken, fix the company not the person
    sop_name = models.CharField(max_length=150, blank=True, default="")
    sop_version = models.CharField(max_length=40, blank=True, default="")
    sop_step = models.CharField(max_length=200, blank=True, default="")
    sop_followed = models.BooleanField(null=True, blank=True)
    sop_adequate = models.BooleanField(null=True, blank=True)

    # workflow
    status = models.CharField(max_length=10, choices=MistakeStatus.choices,
                              default=MistakeStatus.OPEN)
    manager_remarks = models.CharField(max_length=1000, blank=True, default="")
    level3_action = models.CharField(max_length=25, choices=Level3Action.choices, blank=True)
    level3_action_note = models.CharField(max_length=500, blank=True, default="")

    # SLA + escalation: 0 = with manager, 1 = dept head, 2 = founder/admin
    sla_due_at = models.DateTimeField(null=True, blank=True)
    escalation_level = models.PositiveSmallIntegerField(default=0)

    corrective_task = models.OneToOneField("crm.Task", null=True, blank=True,
                                           on_delete=models.SET_NULL,
                                           related_name="mistake_corrective")
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def code(self):
        return f"M-{self.pk:05d}"

    @property
    def sla_overdue(self):
        return bool(self.sla_due_at and self.status != MistakeStatus.RESOLVED
                    and timezone.now() > self.sla_due_at)

    def set_sla(self):
        hours = MistakeSettings.get().hours_for(self.severity)
        self.sla_due_at = timezone.now() + timedelta(hours=hours)

    def __str__(self):
        return f"{self.code} {self.category} ({self.employee})"


class MistakeEvent(models.Model):
    """Permanent audit trail — creation, review, severity change, repeat
    classification, escalation, closure, reopening. Never deleted."""
    mistake = models.ForeignKey(Mistake, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL)
    text = models.CharField(max_length=400)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
