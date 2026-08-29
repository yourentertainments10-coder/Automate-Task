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


REMIND_EVERY_HOURS = 2      # WhatsApp automation C: re-ping while overdue


def send_task_reminders() -> int:
    """Due/overdue tasks ping the assignee — and KEEP pinging every
    REMIND_EVERY_HOURS until the task is done (or the due date moves)."""
    now = timezone.now()
    again_before = now - timezone.timedelta(hours=REMIND_EVERY_HOURS)
    due = (
        Task.objects.exclude(status=TaskStatus.DONE)
        .filter(deleted_at__isnull=True, due_at__isnull=False, due_at__lte=now)
        .filter(Q(reminded_at__isnull=True) | Q(reminded_at__lte=again_before))
        .select_related("assigned_to", "lead")
    )
    sent = 0
    for task in due:
        hours_over = int((now - task.due_at).total_seconds() // 3600)
        state = f"OVERDUE by {hours_over}h" if hours_over >= 1 else "due now"
        wa_template = None
        if hours_over >= 1:  # the approved template reads "OVERDUE by {{3}}"
            wa_template = ("task_overdue_reminde", [
                task.assigned_to.get_full_name() or task.assigned_to.username,
                f"{task.code} · {task.title}",
                f"{hours_over}h",
            ])
        notify(
            task.assigned_to, "task_due",
            (f"Overdue by {hours_over}h" if hours_over >= 1 else "Due now")
            + f" - {task.code}: {task.title}"[:200],
            "\n".join([
                f"Task: {task.code} - {task.title}",
                f"Status: {state} (due {timezone.localtime(task.due_at):%d %b %Y, %I:%M %p})",
                f"Assigned by: {task.created_by.get_full_name() or task.created_by.username}"
                if task.created_by else "Assigned by: -",
            ] + ([task.description[:300]] if task.description else [])
              + ([f"Lead: {task.lead.customer_name}"] if task.lead else [])
              + ["", "Finish it, or open Tasks to post a status update."]),
            link="/tasks",
            wa_template=wa_template,
        )
        task.reminded_at = now
        task.save(update_fields=["reminded_at"])
        sent += 1
    return sent


def send_daily_task_digest(force=False) -> int:
    """One morning message per person: due today / overdue / open counts
    with the top tasks — 'aaj ka plan' in a single ping, never spam."""
    now = timezone.localtime()
    if not force and now.hour < 9:
        return 0
    today = now.date()
    from notifications.models import Notification

    open_tasks = (Task.objects.exclude(status=TaskStatus.DONE)
                  .filter(deleted_at__isnull=True)
                  .select_related("assigned_to").order_by("due_at"))
    per = {}
    for t in open_tasks:
        per.setdefault(t.assigned_to, []).append(t)

    sent = 0
    for user, tasks in per.items():
        if not user.is_active:
            continue
        if Notification.objects.filter(user=user, type="task_daily",
                                       created_at__date=today).exists():
            continue    # once a day, no matter how often the ticker runs
        overdue = [t for t in tasks if t.due_at and t.due_at < now]
        due_today = [t for t in tasks if t.due_at
                     and timezone.localtime(t.due_at).date() == today
                     and t.due_at >= now]
        lines = [f"⚠ {t.code} {t.title[:60]}" for t in overdue[:4]]
        lines += [f"• {t.code} {t.title[:60]} ({timezone.localtime(t.due_at):%H:%M})"
                  for t in due_today[:4]]
        notify(
            user, "task_daily",
            f"Your tasks today - {len(due_today)} due, {len(overdue)} overdue, {len(tasks)} open"[:200],
            ("\n".join(lines) or "Nothing is due today.") + "\n\nOpen Tasks to work through them.",
            link="/tasks",
        )
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
    send_daily_task_digest()            # date-guarded: one per person per day
    purge_expired_attachments()
    from mistakes.sla import escalate_overdue_mistakes  # lazy: avoids app-load cycles
    from mistakes.digests import send_daily_manager_summaries, send_weekly_founder_digest
    escalate_overdue_mistakes()
    send_daily_manager_summaries()      # date-guarded: once a day after 09:00
    send_weekly_founder_digest()        # date-guarded: Mondays only
    return sent
