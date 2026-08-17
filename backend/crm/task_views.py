from collections import Counter
from datetime import timedelta

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasCapability, has_capability
from notifications.service import notify

from .models import (
    EventType, Holiday, LeadEvent, Task, TaskActivity, TaskFrequency,
    TaskStatus, TaskTemplate,
)
from .scoping import can_assign_tasks, can_edit_task, visible_leads, visible_tasks
from .serializers import (
    HolidaySerializer, TaskActivitySerializer, TaskSerializer, TaskTemplateSerializer,
)


def act(task, actor, text):
    TaskActivity.objects.create(task=task, actor=actor, text=text[:300])


def _notify_task_assigned(task, actor):
    if task.assigned_to_id == actor.id:
        return
    due = f" (due {timezone.localtime(task.due_at):%d %b %H:%M})" if task.due_at else ""
    notify(
        task.assigned_to, "task_assigned",
        f"Task assigned: {task.title}",
        (task.description or "") + due
        + (f"\nLead: {task.lead.customer_name}" if task.lead else ""),
        link="/tasks",
    )


def _advance_due(due, frequency):
    if frequency == TaskFrequency.DAILY:
        return due + timedelta(days=1)
    if frequency == TaskFrequency.WEEKLY:
        return due + timedelta(weeks=1)
    # monthly: same day next month (clamped to 28 to stay valid)
    month = due.month % 12 + 1
    year = due.year + (1 if due.month == 12 else 0)
    return due.replace(year=year, month=month, day=min(due.day, 28))


def _spawn_next_occurrence(task, actor):
    """Completing a recurring task creates the next one."""
    if task.frequency == TaskFrequency.ONE_TIME or not task.due_at:
        return None
    nxt = Task.objects.create(
        title=task.title, description=task.description, category=task.category,
        frequency=task.frequency, lead=task.lead, assigned_to=task.assigned_to,
        created_by=task.created_by, priority=task.priority,
        due_at=_advance_due(task.due_at, task.frequency),
    )
    nxt.subscribers.set(task.subscribers.all())
    act(nxt, actor, f"Auto-created next {task.get_frequency_display().lower()} occurrence")
    return nxt


# ---------------------------------------------------------------------------

RANGES = ("today", "yesterday", "this_week", "last_week", "this_month",
          "last_month", "this_year", "all")


def _range_bounds(name, now):
    """(start, end) date bounds in local time; None = unbounded."""
    today = timezone.localtime(now).date()
    if name == "today":
        return today, today
    if name == "yesterday":
        d = today - timedelta(days=1)
        return d, d
    if name == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if name == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=6)
    if name == "this_month":
        return today.replace(day=1), today.replace(day=28) + timedelta(days=10)
    if name == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    if name == "this_year":
        return today.replace(month=1, day=1), today.replace(month=12, day=31)
    return None, None  # all


class TaskViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = TaskSerializer

    def get_queryset(self):
        user = self.request.user
        qs = visible_tasks(user)
        p = self.request.query_params
        scope = p.get("scope")
        if scope == "my":
            qs = qs.filter(assigned_to=user)
        elif scope == "delegated":
            qs = qs.filter(created_by=user).exclude(assigned_to=user)
        elif scope == "subscribed":
            qs = qs.filter(subscribers=user)
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("assigned_to"):
            qs = qs.filter(assigned_to_id=p["assigned_to"])
        if p.get("lead"):
            qs = qs.filter(lead_id=p["lead"])
        if p.get("group"):
            qs = qs.filter(group_id=p["group"])
        if p.get("category"):
            qs = qs.filter(category__iexact=p["category"])
        if p.get("frequency"):
            qs = qs.filter(frequency=p["frequency"])
        if p.get("overdue") == "true":
            qs = qs.exclude(status=TaskStatus.DONE).filter(due_at__lt=timezone.now())
        if p.get("search"):
            qs = qs.filter(title__icontains=p["search"])
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        assignee = serializer.validated_data.get("assigned_to")
        if assignee and assignee.pk != user.pk and not can_assign_tasks(user):
            raise PermissionDenied("Your role cannot assign tasks to other people.")
        lead = serializer.validated_data.get("lead")
        if lead and not visible_leads(user).filter(pk=lead.pk).exists():
            raise PermissionDenied("You cannot link a task to a lead you cannot see.")
        group = serializer.validated_data.get("group")
        if group:
            from workspace.access import user_group_ids, is_workspace_admin
            if group.id not in user_group_ids(user) and not is_workspace_admin(user):
                raise PermissionDenied("You can only create tasks in groups you belong to.")
        task = serializer.save(created_by=user)
        task.subscribers.add(user)  # creator follows their own delegation
        act(task, user, f"Created and assigned to {task.assigned_to.get_full_name() or task.assigned_to.username}")
        if task.lead:
            LeadEvent.objects.create(
                lead=task.lead, type=EventType.NOTE, actor=user,
                body=f"Task created: {task.title}", payload={"task_id": task.pk},
            )
        _notify_task_assigned(task, user)

    def perform_update(self, serializer):
        user = self.request.user
        task = self.get_object()
        if not can_edit_task(user, task):
            raise PermissionDenied("You cannot edit this task.")
        old_assignee, old_status = task.assigned_to, task.status

        new_assignee = serializer.validated_data.get("assigned_to", old_assignee)
        if new_assignee != old_assignee and not can_assign_tasks(user):
            raise PermissionDenied("Your role cannot reassign tasks.")

        updated = serializer.save()

        if updated.status != old_status:
            act(updated, user, f"Status: {old_status} -> {updated.status}")
        if updated.status == TaskStatus.DONE and old_status != TaskStatus.DONE:
            updated.completed_at = timezone.now()
            updated.save(update_fields=["completed_at"])
            if updated.lead:
                LeadEvent.objects.create(
                    lead=updated.lead, type=EventType.NOTE, actor=user,
                    body=f"Task completed: {updated.title}", payload={"task_id": updated.pk},
                )
            _spawn_next_occurrence(updated, user)
        elif updated.status != TaskStatus.DONE and old_status == TaskStatus.DONE:
            updated.completed_at = None
            updated.save(update_fields=["completed_at"])

        if updated.assigned_to != old_assignee:
            act(updated, user, f"Reassigned to {updated.assigned_to.get_full_name() or updated.assigned_to.username}")
            _notify_task_assigned(updated, user)

    def perform_destroy(self, instance):
        if not can_edit_task(self.request.user, instance):
            raise PermissionDenied("You cannot delete this task.")
        instance.delete()

    # ---- extra actions ---------------------------------------------------
    @action(detail=True, methods=["post"])
    def subscribe(self, request, pk=None):
        task = self.get_object()
        task.subscribers.add(request.user)
        return Response({"subscribed": True})

    @action(detail=True, methods=["post"])
    def unsubscribe(self, request, pk=None):
        task = self.get_object()
        task.subscribers.remove(request.user)
        return Response({"subscribed": False})

    @action(detail=False, methods=["get"])
    def categories(self, request):
        cats = (visible_tasks(request.user).exclude(category="")
                .values_list("category", flat=True).distinct())
        return Response(sorted(set(cats), key=str.lower))

    @action(detail=False, methods=["get"])
    def dashboard(self, request):
        """Task dashboard tiles + per-category table.
        Params: range (today|yesterday|this_week|...|all), scope (my|delegated|group),
        category, search. The range applies to a task's due date (falling back
        to its creation date when it has no due date)."""
        user = request.user
        now = timezone.now()
        p = request.query_params
        scope = p.get("scope", "my")

        qs = visible_tasks(user)
        if scope == "my":
            qs = qs.filter(assigned_to=user)
        elif scope == "delegated":
            qs = qs.filter(created_by=user).exclude(assigned_to=user)
        elif scope == "group":
            if not (has_capability(user, "tasks.view_all") or has_capability(user, "tasks.view_department")):
                raise PermissionDenied("Your role has no group report.")
        if p.get("category"):
            qs = qs.filter(category__iexact=p["category"])
        if p.get("search"):
            qs = qs.filter(title__icontains=p["search"])

        start, end = _range_bounds(p.get("range", "this_week"), now)
        rows = []
        for t in qs.values("category", "status", "due_at", "completed_at", "created_at"):
            anchor = timezone.localtime(t["due_at"] or t["created_at"]).date()
            if start and not (start <= anchor <= end):
                continue
            rows.append(t)

        def tally(subset):
            c = Counter()
            for t in subset:
                overdue = t["status"] != TaskStatus.DONE and t["due_at"] and t["due_at"] < now
                if overdue:
                    c["overdue"] += 1
                if t["status"] == TaskStatus.OPEN:
                    c["pending"] += 1
                elif t["status"] == TaskStatus.IN_PROGRESS:
                    c["in_progress"] += 1
                else:
                    c["completed"] += 1
                    if t["due_at"] and t["completed_at"] and t["completed_at"] > t["due_at"]:
                        c["delayed"] += 1
                    else:
                        c["in_time"] += 1
            return {k: c.get(k, 0) for k in
                    ("overdue", "pending", "in_progress", "completed", "in_time", "delayed")}

        by_category = {}
        for t in rows:
            by_category.setdefault(t["category"] or "Uncategorised", []).append(t)
        categories = [
            {"category": cat, "total": len(sub), **tally(sub)}
            for cat, sub in sorted(by_category.items(), key=lambda kv: kv[0].lower())
        ]
        return Response({"tiles": {**tally(rows), "total": len(rows)}, "categories": categories})


class TaskTemplateViewSet(viewsets.ModelViewSet):
    """Templates: everyone reads/uses, only assigners (admin/managers) manage."""
    serializer_class = TaskTemplateSerializer
    queryset = TaskTemplate.objects.select_related("created_by").all()
    pagination_class = None

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [HasCapability.of("tasks.assign")()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class TaskActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """The Activities feed, scoped to tasks the user can see."""
    permission_classes = [IsAuthenticated]
    serializer_class = TaskActivitySerializer

    def get_queryset(self):
        qs = TaskActivity.objects.select_related("actor", "task").filter(
            task__in=visible_tasks(self.request.user))
        p = self.request.query_params
        if p.get("actor"):
            qs = qs.filter(actor_id=p["actor"])
        if p.get("days"):
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=int(p["days"])))
        return qs


class HolidayViewSet(viewsets.ModelViewSet):
    """Company holiday calendar: everyone reads, admin manages."""
    serializer_class = HolidaySerializer
    queryset = Holiday.objects.all()
    pagination_class = None

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [HasCapability.of("settings.manage")()]
