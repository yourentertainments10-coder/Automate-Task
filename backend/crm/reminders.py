"""Follow-up reminders: every open lead whose follow_up_at has passed gets
ONE notification per follow-up (reminded_at tracks the last ping, so a
rescheduled follow-up triggers again, but the same one never repeats).
Called by the in-process ticker (notifications.apps) and by
`manage.py send_reminders` for cron/manual use.
"""
from django.db.models import F, Q
from django.utils import timezone

from notifications.service import notify, notify_follow_up_due

from .models import Lead, OPEN_STATUSES, Task, TaskStatus


def send_task_reminders() -> int:
    """One 'task due' ping per due date -- same dedupe rule as follow-ups."""
    now = timezone.now()
    due = (
        Task.objects.exclude(status=TaskStatus.DONE)
        .filter(due_at__isnull=False, due_at__lte=now)
        .filter(Q(reminded_at__isnull=True) | Q(reminded_at__lt=F("due_at")))
        .select_related("assigned_to", "lead")
    )
    sent = 0
    for task in due:
        notify(
            task.assigned_to, "task_due",
            f"Task due: {task.title}",
            (task.description or "")
            + (f"\nLead: {task.lead.customer_name}" if task.lead else ""),
            link="/tasks",
        )
        task.reminded_at = now
        task.save(update_fields=["reminded_at"])
        sent += 1
    return sent


def send_followup_reminders() -> int:
    now = timezone.now()
    due = (
        Lead.objects.filter(
            status__in=OPEN_STATUSES,
            follow_up_at__isnull=False,
            follow_up_at__lte=now,
            assigned_to__isnull=False,
        )
        .filter(Q(reminded_at__isnull=True) | Q(reminded_at__lt=F("follow_up_at")))
        .select_related("assigned_to")
    )
    sent = 0
    for lead in due:
        notify_follow_up_due(lead)
        lead.reminded_at = now
        lead.save(update_fields=["reminded_at"])
        sent += 1
    return sent + send_task_reminders()
