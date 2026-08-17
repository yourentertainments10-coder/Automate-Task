"""Industry Task Template Directory — a browsable library of ready-made
task templates, deliberately SEPARATE from a company's own private
`crm.TaskTemplate` records.

Content is loaded from structured JSON/CSV (`manage.py load_directory`),
never hand-written in code, so the library can grow to hundreds of
templates without touching the app.
"""
from django.db import models

from crm.models import LeadPriority, TaskFrequency


class Industry(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    icon = models.CharField(max_length=8, blank=True, default="")   # emoji
    description = models.CharField(max_length=300, blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "industries"

    def __str__(self):
        return self.name


class DirectoryTemplate(models.Model):
    """One ready-made template: a titled checklist of steps."""
    industry = models.ForeignKey(Industry, on_delete=models.CASCADE, related_name="templates")
    category = models.CharField(max_length=80, db_index=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    priority = models.CharField(max_length=10, choices=LeadPriority.choices,
                                default=LeadPriority.NORMAL)
    frequency = models.CharField(max_length=10, choices=TaskFrequency.choices,
                                 default=TaskFrequency.ONE_TIME)
    tags = models.JSONField(default=list, blank=True)
    # [{"title": str, "description": str, "offset_days": int}]
    steps = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["industry__order", "category", "name"]
        constraints = [
            models.UniqueConstraint(fields=["industry", "name"], name="uniq_directory_template"),
        ]

    @property
    def step_count(self) -> int:
        return len(self.steps or [])

    def __str__(self):
        return f"{self.industry.name} / {self.category} / {self.name}"
