"""SLA escalation sweep — runs with the reminder ticker (every 5 min) and
via `manage.py send_reminders`.

Unresolved mistake past its SLA deadline climbs one level:
  0 (manager) -> 1 (dept head = the manager's manager) -> 2 (founder/admin).
Every escalation is logged and re-arms the SLA clock at the new level.
"""
from django.utils import timezone

from notifications.service import notify

from .models import Mistake, MistakeStatus


def escalate_overdue_mistakes() -> int:
    from .views import _escalation_target, log
    now = timezone.now()
    overdue = (Mistake.objects
               .exclude(status=MistakeStatus.RESOLVED)
               .filter(sla_due_at__isnull=False, sla_due_at__lt=now,
                       escalation_level__lt=2)
               .select_related("employee", "manager"))
    bumped = 0
    for mistake in overdue:
        mistake.escalation_level += 1
        mistake.set_sla()                      # new clock at the new level
        mistake.save(update_fields=["escalation_level", "sla_due_at"])
        tier = "department head" if mistake.escalation_level == 1 else "founder"
        log(mistake, None, f"SLA missed — auto-escalated to {tier} "
            f"(level {mistake.escalation_level})")
        for target in _escalation_target(mistake, mistake.escalation_level):
            notify(target, "mistake_escalated",
                   f"SLA MISSED: {mistake.code} escalated to you",
                   f"{mistake.category} · {mistake.get_severity_display()} · "
                   f"{mistake.employee.get_full_name() or mistake.employee.username} — "
                   "no action within the deadline.", link="/mistakes")
        bumped += 1
    return bumped
