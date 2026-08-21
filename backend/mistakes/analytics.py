"""M3/M4 analytics over the register.

patterns(days)            -> cross-employee repeat detection ("5 people made
                             this -> question the process, not the people")
founder_summary()         -> Action Required only — never an ops dashboard
department_scores(range)  -> accountability score per department (M4)
mistake_penalties(users, start, end) -> per-user penalty inputs for the
                             employee score (M4, merged into employees_report)
"""
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from accounts.models import Department

from .models import Mistake, MistakeStatus, Severity

PROCESS_SUSPECT_PEOPLE = 3          # distinct employees on one category -> process smell
SEVERITY_WEIGHT = {Severity.LOW: 1, Severity.MEDIUM: 3, Severity.HIGH: 6, Severity.CRITICAL: 10}
MAX_EMPLOYEE_PENALTY = 30           # the score can lose at most this much to mistakes


def patterns(days: int = 90, queryset=None) -> dict:
    since = timezone.now() - timedelta(days=days)
    qs = (queryset if queryset is not None else Mistake.objects.all()).filter(created_at__gte=since)
    by_cat = defaultdict(lambda: {"count": 0, "employees": set(), "departments": set(),
                                  "loss": Decimal("0"), "repeats": 0})
    by_person = Counter()
    for m in qs.select_related("employee"):
        row = by_cat[m.category]
        row["count"] += 1
        row["employees"].add(m.employee_id)
        if m.department:
            row["departments"].add(m.department)
        row["loss"] += m.financial_loss or 0
        if m.occurrence_level > 1:
            row["repeats"] += 1
        by_person[(m.employee_id, m.employee.get_full_name() or m.employee.username,
                   m.category)] += 1

    cats = []
    for cat, r in by_cat.items():
        people = len(r["employees"])
        suspect = people >= PROCESS_SUSPECT_PEOPLE
        cats.append({
            "category": cat, "count": r["count"], "distinct_employees": people,
            "departments": sorted(r["departments"]), "financial_loss": float(r["loss"]),
            "repeats": r["repeats"], "process_suspect": suspect,
            "message": (f"{people} different people made this in {days} days — "
                        "question the PROCESS, not the people.") if suspect
            else (f"{r['count']} occurrence(s) by {people} person(s)."),
        })
    cats.sort(key=lambda c: (-int(c["process_suspect"]), -c["count"]))
    offenders = [{"user": uid, "name": name, "category": cat, "count": n}
                 for (uid, name, cat), n in by_person.most_common() if n >= 2][:10]
    return {"days": days, "categories": cats, "repeat_offenders": offenders}


def founder_summary() -> dict:
    now = timezone.now()
    month_start = timezone.localtime(now).date().replace(day=1)
    open_qs = Mistake.objects.exclude(status=MistakeStatus.RESOLVED)
    return {
        "critical_open": open_qs.filter(severity=Severity.CRITICAL).count(),
        "high_open": open_qs.filter(severity=Severity.HIGH).count(),
        "sla_missed": open_qs.filter(sla_due_at__lt=now).count(),
        "escalated_to_founder": open_qs.filter(escalation_level__gte=2).count(),
        "level3_open": open_qs.filter(occurrence_level__gte=3).count(),
        "loss_this_month": float(sum((m.financial_loss or 0) for m in
                                     Mistake.objects.filter(created_at__date__gte=month_start))),
        "open_total": open_qs.count(),
        "patterns": [c for c in patterns(90)["categories"] if c["process_suspect"]][:5],
        "repeat_offenders": patterns(90)["repeat_offenders"][:5],
    }


def department_scores(start=None, end=None) -> dict:
    """Score = 100 − repeat penalty − SLA penalty − loss penalty + improvement.
    Every component is returned so the number is explainable."""
    qs = Mistake.objects.all()
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    # previous period of the same length, for the improvement signal
    prev_qs = Mistake.objects.none()
    if start and end:
        span = (end - start).days + 1
        prev_qs = Mistake.objects.filter(created_at__date__gte=start - timedelta(days=span),
                                         created_at__date__lt=start)
    prev_counts = Counter(prev_qs.values_list("department", flat=True))

    rows = []
    for dept, label in Department.choices:
        sub = list(qs.filter(department=dept))
        if not sub and not prev_counts.get(dept):
            continue
        total = len(sub)
        repeats = sum(1 for m in sub if m.occurrence_level > 1)
        resolved = [m for m in sub if m.status == MistakeStatus.RESOLVED and m.resolved_at]
        within = sum(1 for m in resolved if m.sla_due_at and m.resolved_at <= m.sla_due_at)
        sla_rate = round(100 * within / len(resolved), 1) if resolved else None
        loss = float(sum((m.financial_loss or 0) for m in sub))
        prev = prev_counts.get(dept, 0)
        improvement = round(100 * (prev - total) / prev, 1) if prev else None

        repeat_pen = min(30, repeats * 5)
        sla_pen = round((100 - sla_rate) * 0.3, 1) if sla_rate is not None else 0
        loss_pen = 0 if loss < 5000 else 10 if loss < 50000 else 20
        improv_bonus = 5 if (improvement or 0) >= 20 else 0
        score = max(0, min(100, round(100 - repeat_pen - sla_pen - loss_pen + improv_bonus, 1)))
        rows.append({
            "department": dept, "label": label, "mistakes": total, "repeats": repeats,
            "sla_compliance": sla_rate, "financial_loss": loss,
            "improvement_pct": improvement, "score": score,
            "breakdown": {"repeat_penalty": repeat_pen, "sla_penalty": sla_pen,
                          "loss_penalty": loss_pen, "improvement_bonus": improv_bonus},
        })
    rows.sort(key=lambda r: -r["score"])
    return {"rows": rows,
            "formula": "100 − 5/repeat (max 30) − 0.3×(100 − SLA%) − loss tier (0/10/20) "
                       "+ 5 if ≥20% fewer mistakes than the previous period"}


def mistake_penalties(user_ids, start=None, end=None) -> dict:
    """Per user: severity-weighted penalty (repeats count double), counts and
    action-completion rate — feeds the employee score (M4)."""
    qs = Mistake.objects.filter(employee_id__in=user_ids)
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    out = {}
    for m in qs:
        r = out.setdefault(m.employee_id, {"mistakes": 0, "repeats": 0, "penalty": 0,
                                           "actioned": 0})
        r["mistakes"] += 1
        w = SEVERITY_WEIGHT.get(m.severity, 3)
        if m.occurrence_level > 1:
            r["repeats"] += 1
            w *= 2
        r["penalty"] += w
        if m.status != MistakeStatus.OPEN:      # explained or resolved = acted on
            r["actioned"] += 1
    for r in out.values():
        r["penalty"] = min(MAX_EMPLOYEE_PENALTY, r["penalty"])
        r["action_rate"] = round(100 * r["actioned"] / r["mistakes"], 1) if r["mistakes"] else None
    return out
