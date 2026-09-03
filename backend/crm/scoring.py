"""One place that answers "what is this person's score?".

The Reports page and the day-end WhatsApp digest MUST agree -- a score that
reads 82 on the dashboard and 74 on WhatsApp destroys trust in both. So the
weights and the rules live here and both callers import them.

The rules, unchanged from the Reports page:
  * only tasks somebody ELSE assigned are scored (self-assigned earn nothing)
  * a task spawned to correct a MISTAKE is not scored either -- the mistake
    penalty already covers that error, and charging the effort ratio as well
    would dock the same person twice for one mistake, invisibly
  * score = 60 x on-time rate + 40 x (effort earned / effort assigned)
  * logged mistakes subtract from it
"""
from django.utils import timezone

from .models import Task, TaskStatus

ON_TIME_WEIGHT = 60
EFFORT_WEIGHT = 40


def corrective_task_ids(task_ids) -> set[int]:
    """Which of these tasks exist only because a mistake was logged."""
    if not task_ids:
        return set()
    from mistakes.models import Mistake
    return set(Mistake.objects
               .filter(corrective_task_id__in=task_ids)
               .values_list("corrective_task_id", flat=True))


def score_for(user, start=None, end=None) -> dict:
    """Counts + score for one person over a date window (None = all time).
    Returns score=None when there is nothing scoreable, exactly like the
    Reports page does."""
    now = timezone.now()
    qs = Task.objects.filter(assigned_to=user, deleted_at__isnull=True)
    rows = list(qs.values("id", "created_by_id", "status", "due_at",
                          "completed_at", "created_at", "effort_minutes"))
    corrective = corrective_task_ids([r["id"] for r in rows])

    completed = pending = overdue = 0
    sc_completed = sc_in_time = sc_assigned = sc_earned = 0
    for t in rows:
        anchor = timezone.localtime(t["due_at"] or t["created_at"]).date()
        if start and not (start <= anchor <= end):
            continue
        # not scored: your own task, or one raised to correct a mistake
        own = t["created_by_id"] == user.pk or t["id"] in corrective
        effort = t["effort_minutes"] or 0
        if t["status"] == TaskStatus.DONE:
            completed += 1
            late = (t["due_at"] and t["completed_at"]
                    and t["completed_at"] > t["due_at"])
            if not own:
                sc_completed += 1
                sc_earned += effort
                if not late:
                    sc_in_time += 1
        else:
            pending += 1
            if t["due_at"] and t["due_at"] < now:
                overdue += 1
        if not own:
            sc_assigned += effort

    on_time = (sc_in_time / sc_completed) if sc_completed else None
    ratio = min(1.0, sc_earned / sc_assigned) if sc_assigned else None
    if on_time is None:
        score = None
    elif ratio is None:
        score = round(100 * on_time, 1)
    else:
        score = round(ON_TIME_WEIGHT * on_time + EFFORT_WEIGHT * ratio, 1)

    if score is not None:
        from mistakes.analytics import mistake_penalties
        pen = mistake_penalties([user.pk], start, end).get(user.pk, {})
        score = round(max(0, score - (pen.get("penalty") or 0)), 1)

    return {"completed": completed, "pending": pending, "overdue": overdue,
            "scored_completed": sc_completed, "score": score}
