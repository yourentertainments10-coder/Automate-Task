"""M3 digests — managers get ONE daily accountability summary, the founder
gets ONE concise weekly executive digest. Driven by the 5-minute reminder
ticker with date guards on MistakeSettings, so they fire once, after 09:00,
and never spam.
"""
from django.utils import timezone

from accounts.models import User
from notifications.service import notify

from .analytics import founder_summary, patterns
from .models import Mistake, MistakeSettings, MistakeStatus

SEND_AFTER_HOUR = 9


def _admins():
    from accounts.permissions import ROLE_CAPABILITIES
    roles = [r for r, caps in ROLE_CAPABILITIES.items() if "tasks.view_all" in caps]
    return User.objects.filter(is_active=True, role__in=roles)


def send_daily_manager_summaries(force=False) -> int:
    cfg = MistakeSettings.get()
    now = timezone.localtime()
    if not force and (cfg.last_daily_digest == now.date() or now.hour < SEND_AFTER_HOUR):
        return 0
    sent = 0
    open_qs = Mistake.objects.exclude(status=MistakeStatus.RESOLVED).select_related("employee")
    for manager in User.objects.filter(is_active=True, accountable_mistakes__in=open_qs).distinct():
        mine = [m for m in open_qs if m.manager_id == manager.pk]
        overdue = [m for m in mine if m.sla_overdue]
        waiting = [m for m in mine if m.status == MistakeStatus.EXPLAINED]
        repeats = [m for m in mine if m.occurrence_level > 1]
        body = (f"{len(mine)} open · {len(waiting)} waiting for your review · "
                f"{len(overdue)} past SLA · {len(repeats)} repeat error(s).")
        if overdue:
            body += "\nPast SLA: " + ", ".join(
                f"{m.code} ({m.employee.get_full_name() or m.employee.username})" for m in overdue[:5])
        notify(manager, "mistake_digest", "Daily accountability summary", body, link="/mistakes")
        sent += 1
    cfg.last_daily_digest = now.date()
    cfg.save(update_fields=["last_daily_digest"])
    return sent


def send_weekly_founder_digest(force=False) -> int:
    cfg = MistakeSettings.get()
    now = timezone.localtime()
    this_week = now.date() - timezone.timedelta(days=now.weekday())   # Monday
    if not force and (now.weekday() != 0 or cfg.last_weekly_digest == this_week
                      or now.hour < SEND_AFTER_HOUR):
        return 0
    s = founder_summary()
    pats = patterns(7)
    body = (f"Open: {s['open_total']} · Critical {s['critical_open']} · High {s['high_open']} · "
            f"SLA missed {s['sla_missed']} · Escalated to you {s['escalated_to_founder']} · "
            f"3rd occurrences {s['level3_open']}\n"
            f"Financial loss this month: ₹{s['loss_this_month']:,.0f}")
    suspects = [c for c in pats["categories"] if c["process_suspect"]]
    if suspects:
        body += "\nProcess smells this week: " + "; ".join(
            f"{c['category']} ({c['distinct_employees']} people)" for c in suspects[:3])
    if s["repeat_offenders"]:
        body += "\nRepeat offenders (90d): " + ", ".join(
            f"{o['name']} ×{o['count']} {o['category']}" for o in s["repeat_offenders"][:3])
    sent = 0
    for admin in _admins():
        notify(admin, "mistake_digest", "Weekly executive digest — mistakes & accountability",
               body, link="/mistakes")
        sent += 1
    cfg.last_weekly_digest = this_week
    cfg.save(update_fields=["last_weekly_digest"])
    return sent
