"""Follow-up reminders: every open lead whose follow_up_at has passed gets
ONE notification per follow-up (reminded_at tracks the last ping, so a
rescheduled follow-up triggers again, but the same one never repeats).
Called by the in-process ticker (notifications.apps) and by
`manage.py send_reminders` for cron/manual use.

Also home to the attachment-retention sweep: files on finished tasks are
kept TASK_ATTACHMENT_RETENTION_DAYS (default 7) after completion, then
deleted from disk and DB (reviewer's storage rule, 19 Aug demo).
"""
import os

from django.db.models import F, Q
from django.utils import timezone

from notifications.service import notify, notify_follow_up_due

from .models import Lead, OPEN_STATUSES, Task, TaskAttachment, TaskStatus


def purge_expired_attachments() -> int:
    """Delete attachments on tasks completed more than the retention window
    ago. Only DONE tasks with a completed_at qualify — open/deleted-but-open
    tasks keep their files."""
    days = int(os.environ.get("TASK_ATTACHMENT_RETENTION_DAYS", "7"))
    if days <= 0:  # 0 or negative disables the sweep entirely
        return 0
    cutoff = timezone.now() - timezone.timedelta(days=days)
    expired = TaskAttachment.objects.filter(
        task__status=TaskStatus.DONE,
        task__completed_at__isnull=False,
        task__completed_at__lt=cutoff,
    )
    removed = 0
    for att in expired:
        if att.file:
            att.file.delete(save=False)  # remove from storage first
        att.delete()
        removed += 1
    return removed


def send_task_reminders() -> int:
    """One 'task due' ping per due date -- same dedupe rule as follow-ups."""
    now = timezone.now()
    due = (
        Task.objects.exclude(status=TaskStatus.DONE)
        .filter(deleted_at__isnull=True, due_at__isnull=False, due_at__lte=now)
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
    sent += send_task_reminders()
    purge_expired_attachments()
    from mistakes.sla import escalate_overdue_mistakes  # lazy: avoids app-load cycles
    escalate_overdue_mistakes()
    return sent
