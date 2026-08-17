"""Admin/manager dashboard aggregates. Everything is computed off
visible_leads(user), so a sales manager automatically gets a department
dashboard while admin sees the whole business."""
from collections import Counter
from datetime import timedelta

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import HasCapability
from intake.models import InboundMessage

from .models import Lead, LeadEvent, LeadSource, LeadStatus, OPEN_STATUSES, TaskStatus
from .scoping import visible_leads, visible_tasks

DAYS = 14


@api_view(["GET"])
@permission_classes([HasCapability.of("dashboard.view")])
def dashboard(request):
    now = timezone.now()
    leads = visible_leads(request.user)
    rows = list(leads.values("id", "status", "source", "priority", "assigned_to_id",
                             "follow_up_at", "estimated_value", "created_at"))

    won = sum(1 for r in rows if r["status"] == LeadStatus.WON)
    lost = sum(1 for r in rows if r["status"] == LeadStatus.LOST)
    open_rows = [r for r in rows if r["status"] in OPEN_STATUSES]
    overdue = [r for r in open_rows if r["follow_up_at"] and r["follow_up_at"] < now]
    upcoming = [r for r in open_rows if r["follow_up_at"] and r["follow_up_at"] >= now]

    task_rows = list(visible_tasks(request.user).values("status", "assigned_to_id", "due_at"))
    open_tasks = [t for t in task_rows if t["status"] != TaskStatus.DONE]

    tiles = {
        "open_tasks": len(open_tasks),
        "overdue_tasks": sum(1 for t in open_tasks if t["due_at"] and t["due_at"] < now),
        "total": len(rows),
        "new": sum(1 for r in rows if r["status"] == LeadStatus.NEW),
        "active": len(open_rows),
        "won": won,
        "lost": lost,
        "overdue": len(overdue),
        "pending_followups": len(overdue) + len(upcoming),
        "conversion_pct": round(100 * won / (won + lost)) if (won + lost) else 0,
        "pipeline_value": float(sum(r["estimated_value"] or 0 for r in open_rows)),
    }

    by_status = Counter(r["status"] for r in rows)
    status_dist = [
        {"status": value, "label": label, "count": by_status.get(value, 0)}
        for value, label in LeadStatus.choices
    ]

    # Leads created per day, local dates, last DAYS days
    # Local dates throughout -- `now.date()` is the UTC date, which drifts a
    # day ahead of IST every evening and would drop today's leads from the chart.
    start = timezone.localdate() - timedelta(days=DAYS - 1)
    per_day_counter = Counter(
        timezone.localtime(r["created_at"]).date() for r in rows
        if timezone.localtime(r["created_at"]).date() >= start
    )
    per_day = [
        {"date": (start + timedelta(days=i)).isoformat(),
         "count": per_day_counter.get(start + timedelta(days=i), 0)}
        for i in range(DAYS)
    ]

    # Employee performance across the visible scope
    per_user = {}
    for r in rows:
        uid = r["assigned_to_id"]
        if not uid:
            continue
        agg = per_user.setdefault(uid, {"total": 0, "open": 0, "won": 0, "lost": 0, "overdue": 0})
        agg["total"] += 1
        if r["status"] in OPEN_STATUSES:
            agg["open"] += 1
            if r["follow_up_at"] and r["follow_up_at"] < now:
                agg["overdue"] += 1
        elif r["status"] == LeadStatus.WON:
            agg["won"] += 1
        else:
            agg["lost"] += 1
    tasks_per_user = Counter(t["assigned_to_id"] for t in open_tasks)
    for uid, count in tasks_per_user.items():
        per_user.setdefault(uid, {"total": 0, "open": 0, "won": 0, "lost": 0, "overdue": 0})
    names = {u.pk: u for u in User.objects.filter(pk__in=per_user)}
    employees = sorted(
        ({"id": uid, "name": names[uid].get_full_name() or names[uid].username,
          "role": names[uid].get_role_display(),
          "open_tasks": tasks_per_user.get(uid, 0), **agg}
         for uid, agg in per_user.items() if uid in names),
        key=lambda e: (-e["won"], -e["total"]),
    )

    # Source performance
    by_source = {}
    for r in rows:
        agg = by_source.setdefault(r["source"], {"total": 0, "won": 0})
        agg["total"] += 1
        if r["status"] == LeadStatus.WON:
            agg["won"] += 1
    source_labels = dict(LeadSource.choices)
    sources = sorted(
        ({"source": s, "label": source_labels.get(s, s), "total": a["total"], "won": a["won"],
          "conversion_pct": round(100 * a["won"] / a["total"]) if a["total"] else 0}
         for s, a in by_source.items()),
        key=lambda s: -s["total"],
    )

    lead_ids = [r["id"] for r in rows]
    recent_inbound = [
        {"channel": m.channel, "sender": m.sender_name or m.sender, "body": m.body[:120],
         "status": m.status, "lead_name": m.lead.customer_name if m.lead else None,
         "created_at": m.created_at}
        for m in InboundMessage.objects.select_related("lead")
        .filter(lead_id__in=lead_ids)[:8]
    ]

    recent_events = [
        {"type": e.type, "body": e.body[:120], "lead_name": e.lead.customer_name,
         "actor": (e.actor.get_full_name() or e.actor.username) if e.actor else "System",
         "created_at": e.created_at}
        for e in LeadEvent.objects.select_related("lead", "actor")
        .filter(lead_id__in=lead_ids)[:10]
    ]

    return Response({
        "tiles": tiles, "status_dist": status_dist, "per_day": per_day,
        "employees": employees, "sources": sources,
        "recent_inbound": recent_inbound, "recent_events": recent_events,
    })
