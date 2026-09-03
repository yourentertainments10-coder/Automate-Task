from collections import Counter
from datetime import timedelta

from django.db.models import Count, F, Q
from django.utils import timezone
from rest_framework import status as http, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import HasCapability, has_capability
from notifications.service import notify

from .ai_tasks import draft_task, proofread, review_sentence, summarize_task
from .models import (
    ChangeRequestStatus, EventType, Holiday, LeadEvent, Task, TaskActivity,
    TaskAttachment, TaskCategory, TaskChangeRequest, TaskChecklistItem,
    TaskFrequency, TaskSettings, TaskStatus, TaskTemplate,
)
from .scoping import (
    assignable_users, can_assign_to, can_edit_task, visible_leads, visible_tasks,
)
from .serializers import (
    HolidaySerializer, TaskActivitySerializer, TaskAttachmentSerializer,
    TaskChangeRequestSerializer, TaskSerializer, TaskSettingsSerializer,
    TaskTemplateSerializer, UserBriefSerializer,
)


def act(task, actor, text):
    TaskActivity.objects.create(task=task, actor=actor, text=text[:300])


def _admins():
    from accounts.permissions import ROLE_CAPABILITIES
    admin_roles = [r for r, caps in ROLE_CAPABILITIES.items() if "tasks.view_all" in caps]
    return User.objects.filter(is_active=True, role__in=admin_roles)


def NL_JOIN(lines):
    """Join notification body lines. Named so the literal newline never has to
    survive a shell round-trip in tooling."""
    return chr(10).join(lines)


def _category_approvers(requester):
    """Who can turn a category request into a real category: the requester's
    own manager if they may assign tasks, otherwise the admins."""
    manager = requester.reporting_manager
    if manager and manager.is_active and has_capability(manager, "tasks.assign"):
        return [manager]
    return list(_admins().exclude(pk=requester.pk))


def _approvers_for(req: TaskChangeRequest):
    """Who decides a Modification Request. The rule is "one step up from
    the person asking", never a broadcast to every admin:

      assignee asks           -> the person who GAVE them the task
      creator asks (own task) -> that person's reporting manager
      nobody on file          -> admins, as a last resort only

    An approver who would rather not decide can still Escalate to admin."""
    task = req.task
    if req.requested_by_id != task.created_by_id and task.created_by \
            and task.created_by.is_active:
        return [task.created_by]
    manager = req.requested_by.reporting_manager
    if manager and manager.is_active and manager.pk != req.requested_by_id:
        return [manager]
    return list(_admins().exclude(pk=req.requested_by_id))


def _change_request_body(req: TaskChangeRequest, approver) -> str:
    """The approval email/WhatsApp has to stand on its own: WHICH task, WHOSE
    task it is, what exactly changes, and why it reached this person. Without
    that an approver only sees "wants to change due_at, assigned_to" and has
    no idea why it landed in their inbox."""
    task = req.task

    def who(u):
        return (u.get_full_name() or u.username) if u else "-"

    if approver.id == task.created_by_id:
        because = "This is yours to decide because you gave out this task."
    elif approver.id == getattr(req.requested_by, "reporting_manager_id", None):
        because = ("This is yours to decide because "
                   f"{who(req.requested_by)} reports to you and this is their own task.")
    elif has_capability(approver, "tasks.view_all"):
        because = ("This reached you as an admin because there is no reporting "
                   f"manager on file for {who(req.requested_by)} - set one in "
                   "My Team so these stop coming to admins.")
    else:
        because = "You have been asked to review this request."
    lines = [
        f"Task: {task.code} - {task.title}",
        f"Assigned to: {who(task.assigned_to)}",
        f"Task created by: {who(task.created_by)}",
        f"Change requested by: {who(req.requested_by)}",
        "",
        "Proposed changes:",
    ]
    lines += [f"  - {line}" for line in req.describe()]
    lines += ["", f"Reason: {req.reason[:300]}", "", because,
              "Open Tasks -> Requests to approve, reject or escalate."]
    return "\n".join(lines)


def can_review_request(user, req: TaskChangeRequest) -> bool:
    """Derived from _approvers_for, so routing and permission never drift."""
    if req.requested_by_id == user.id:
        return False                       # never your own request
    if req.escalated:                      # escalated: only admin decides
        return has_capability(user, "tasks.view_all")
    if any(a.pk == user.pk for a in _approvers_for(req)):
        return True
    return has_capability(user, "tasks.view_all")   # admin backstop


def _notify_task_assigned(task, actor):
    """WhatsApp automation A: the assignment ping carries ALL the details —
    one message tells the whole story."""
    if task.assigned_to_id == actor.id:
        return
    bits = [f"{task.code} · {task.title}"]
    if task.description:
        bits.append(task.description[:300])
    facts = []
    if task.due_at:
        facts.append(f"Due: {timezone.localtime(task.due_at):%d %b %H:%M}")
    if task.effort_minutes:
        facts.append(f"Effort: {task.effort_minutes}m")
    if task.priority != "normal":
        facts.append(f"Priority: {task.get_priority_display()}")
    if task.category:
        facts.append(f"Category: {task.category}")
    if task.frequency != TaskFrequency.ONE_TIME:
        facts.append(f"Repeats: {task.get_frequency_display()}"
                     + (f" till {task.repeat_until:%d %b}" if task.repeat_until else ""))
    if task.lead:
        facts.append(f"Lead: {task.lead.customer_name}")
    if facts:
        bits.append(" · ".join(facts))
    who = actor.get_full_name() or actor.username
    bits.append(f"Assigned by: {who} · {timezone.localtime():%d %b %Y, %I:%M %p}")
    notify(
        task.assigned_to, "task_assigned",
        f"Task assigned by {who}: {task.title}"[:200],
        "\n".join(bits),
        link=f"/tasks/{task.id}",
        wa_template=("new_task_assigne", [
            task.assigned_to.get_full_name() or task.assigned_to.username,
            f"{task.code} · {task.title}",
            task.description or "—",
            f"{task.get_priority_display()} (by {who})",
            f"{timezone.localtime(task.due_at):%d %b %Y, %I:%M %p}" if task.due_at else "Not set",
        ]),
    )


def _notify_task_completed(task, actor):
    """WhatsApp automation B: completion goes to EVERYONE involved — the
    creator, the assignee (when someone else closed it) and all followers
    (in-loop subscribers)."""
    took = f" — took {task.actual_minutes}m" if task.actual_minutes else ""
    assigned = f" (assigned {task.effort_minutes}m)" if task.effort_minutes else ""
    body = (f"{task.code} · {task.title}\nCompleted by "
            f"{actor.get_full_name() or actor.username} on "
            f"{timezone.localtime():%d %b %Y, %I:%M %p}{took}{assigned}."
            + (f"\nNote: {task.completion_note[:200]}" if task.completion_note else ""))
    when = f"{timezone.localtime():%d %b %Y, %I:%M %p}"
    targets = {task.created_by, task.assigned_to}
    targets.update(task.subscribers.all())
    for target in targets:
        if target and target.is_active and target.pk != actor.pk:
            notify(target, "task_completed",
                   f"✅ Completed: {task.title}"[:200], body, link=f"/tasks/{task.id}",
                   wa_template=("task_completed_alert", [
                       target.get_full_name() or target.username,
                       f"{task.code} · {task.title}",
                       actor.get_full_name() or actor.username,
                       when + (took or "") + (assigned or ""),
                       task.completion_note or "—",
                   ]))


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
    """Completing a recurring task creates the next one -- unless the
    recurrence's end date (repeat_until) has been reached."""
    if task.frequency == TaskFrequency.ONE_TIME or not task.due_at:
        return None
    next_due = _advance_due(task.due_at, task.frequency)
    if task.repeat_until and timezone.localtime(next_due).date() > task.repeat_until:
        act(task, actor, f"Recurrence ended (until {task.repeat_until})")
        return None
    nxt = Task.objects.create(
        title=task.title, description=task.description, category=task.category,
        frequency=task.frequency, repeat_until=task.repeat_until,
        effort_minutes=task.effort_minutes,
        lead=task.lead, assigned_to=task.assigned_to,
        created_by=task.created_by, priority=task.priority,
        due_at=next_due,
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
        first = today.replace(day=1)
        next_first = (first + timedelta(days=32)).replace(day=1)
        return first, next_first - timedelta(days=1)
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
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        user = self.request.user
        p = self.request.query_params
        scope = p.get("scope")
        if scope == "deleted":
            # The Deleted Tasks bin -- admin only
            if not has_capability(user, "tasks.view_all"):
                from rest_framework.exceptions import PermissionDenied as PD
                raise PD("Only an admin can view deleted tasks.")
            return (visible_tasks(user, include_deleted=True)
                    .filter(deleted_at__isnull=False).order_by("-deleted_at"))
        qs = visible_tasks(user)
        if scope == "my":
            qs = qs.filter(assigned_to=user)
        elif scope == "delegated":
            qs = qs.filter(created_by=user).exclude(assigned_to=user)
        elif scope == "subscribed":
            qs = qs.filter(subscribers=user)
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("assigned_to"):
            # "All Tasks" filters by one person or several at once
            ids = [i for i in p["assigned_to"].split(",") if i.strip().isdigit()]
            qs = qs.filter(assigned_to_id__in=ids) if ids else qs.none()
        if p.get("department"):
            qs = qs.filter(assigned_to__department__in=p["department"].split(","))
        if p.get("manager"):
            # everyone reporting to this manager (their team's tasks in one go)
            qs = qs.filter(assigned_to__reporting_manager_id=p["manager"])
        if p.get("created_by"):
            qs = qs.filter(created_by_id=p["created_by"])
        if p.get("priority"):
            qs = qs.filter(priority__in=p["priority"].split(","))
        if p.get("lead"):
            qs = qs.filter(lead_id=p["lead"])
        if p.get("group"):
            qs = qs.filter(group_id=p["group"])
        if p.get("category"):
            qs = qs.filter(category__iexact=p["category"])
        if p.get("frequency"):
            qs = qs.filter(frequency=p["frequency"])
        if p.get("recurring") == "true":
            qs = qs.exclude(frequency=TaskFrequency.ONE_TIME)
        if p.get("overdue") == "true":
            qs = qs.exclude(status=TaskStatus.DONE).filter(due_at__lt=timezone.now())
        if p.get("search"):
            from django.db.models import Q as _Q
            term = p["search"].strip()
            clause = (_Q(title__icontains=term) | _Q(description__icontains=term)
                      | _Q(assigned_to__first_name__icontains=term)
                      | _Q(assigned_to__last_name__icontains=term)
                      | _Q(assigned_to__username__icontains=term))
            # "code" is a property (T-00042), so match its digits against the pk
            digits = term.lstrip("Tt-").lstrip("0")
            if digits.isdigit():
                clause |= _Q(pk=int(digits))
            qs = qs.filter(clause)
        return qs

    def _resolve_category(self, user, department, name):
        """Employees must pick a managed category; managers/admin typing a
        new name create it on the fly (the inline 'Add Category')."""
        name = (name or "").strip()
        if not name:
            return ""
        from django.db.models import Q as _Q
        match = (TaskCategory.objects.filter(name__iexact=name)
                 .filter(_Q(department="") | _Q(department=department or ""))
                 .order_by("-active").first())
        if match and match.active:
            return match.name           # canonical casing
        if has_capability(user, "tasks.assign"):
            if match:                   # was deactivated — bring it back
                match.active = True
                match.save(update_fields=["active"])
                return match.name
            TaskCategory.objects.create(name=name[:60], department=department or "",
                                        created_by=user)
            return name[:60]
        raise ValidationError({
            "category": "Pick a category from the list — only managers can add new ones."})

    def perform_create(self, serializer):
        user = self.request.user
        assignee = serializer.validated_data.get("assigned_to")
        if assignee and not can_assign_to(user, assignee):
            raise PermissionDenied(
                "You can assign tasks to people at your level or below — "
                "not to someone senior to you.")
        # B6: effort is mandatory when creating a task by hand -- scoring
        # depends on it (system-created tasks from forms/templates are exempt).
        missing = {}
        if not serializer.validated_data.get("effort_minutes"):
            missing["effort_minutes"] = "Effort is required — how long should this task take?"
        # No due date means no reminder, no overdue flag and no on-time score,
        # so the task quietly falls out of every report. Make it mandatory.
        due = serializer.validated_data.get("due_at")
        if not due:
            missing["due_at"] = "Due date is required — reminders and on-time scoring need it."
        elif due <= timezone.now():
            local = timezone.localtime(due)
            missing["due_at"] = (
                f"That deadline is already past ({local:%d %b %Y, %I:%M %p}). "
                "Check AM/PM — did you mean "
                f"{(local + timedelta(hours=12)):%I:%M %p}?")
        if missing:
            raise ValidationError(missing)
        serializer.validated_data["category"] = self._resolve_category(
            user,
            serializer.validated_data.get("department", ""),
            serializer.validated_data.get("category", ""))
        # E1: sub-tasks are one level deep and only under tasks you can see
        parent = serializer.validated_data.get("parent")
        if parent:
            if parent.deleted_at or not visible_tasks(user).filter(pk=parent.pk).exists():
                raise ValidationError({"parent": "Unknown parent task."})
            if parent.parent_id:
                raise ValidationError({"parent": "Sub-tasks can't have their own sub-tasks."})
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
        # The person GIVING the task breaks it into steps -- the assignee
        # ticks them off one by one and cannot finish until all are done.
        steps = self.request.data.get("checklist") or []
        if isinstance(steps, list):
            for i, step in enumerate(steps[:30]):
                text = str(step).strip()
                if text:
                    TaskChecklistItem.objects.create(
                        task=task, text=text[:200], order=i,
                        created_by=user)
        # B7: "In-Loop" — colleagues added at creation start following the task
        in_loop = self.request.data.get("in_loop") or []
        if isinstance(in_loop, list):
            for uid in in_loop[:20]:
                colleague = User.objects.filter(pk=uid, is_active=True).first()
                if colleague and colleague.pk != user.pk:
                    task.subscribers.add(colleague)
                    notify(colleague, "task_inloop",
                           f"Kept in the loop - {task.code}: {task.title}"[:200],
                           "\n".join([
                               f"Task: {task.code} - {task.title}",
                               f"Assigned to: {task.assigned_to.get_full_name() or task.assigned_to.username}",
                               f"Added you: {user.get_full_name() or user.username}",
                               f"Due: {timezone.localtime(task.due_at):%d %b %Y, %I:%M %p}"
                               if task.due_at else "Due: not set",
                               "",
                               "You are only following this - it is not assigned to you.",
                               "It shows under Tasks > Subscribed.",
                           ]),
                           link=f"/tasks/{task.id}",
                           wa_template=("task_inloop_alert", [
                               colleague.get_full_name() or colleague.username,
                               f"{task.code} - {task.title}",
                               task.assigned_to.get_full_name() or task.assigned_to.username,
                               user.get_full_name() or user.username,
                               f"{timezone.localtime(task.due_at):%d %b %Y, %I:%M %p}"
                               if task.due_at else "Not set",
                           ]))
        act(task, user, f"Created and assigned to {task.assigned_to.get_full_name() or task.assigned_to.username}")
        if task.lead:
            LeadEvent.objects.create(
                lead=task.lead, type=EventType.NOTE, actor=user,
                body=f"Task created: {task.title}", payload={"task_id": task.pk},
            )
        _notify_task_assigned(task, user)

    def perform_update(self, serializer):
        """B1 edit lockdown (Sir's anti-manipulation rule):
        - Admin: full edit, logged.
        - Assignee: STATUS ONLY (their whole job is moving it forward).
        - Everyone else -- including the creator: no direct edits. Propose a
          Modification Request instead."""
        user = self.request.user
        task = self.get_object()
        is_admin = has_capability(user, "tasks.view_all")
        data = serializer.validated_data

        if not is_admin:
            changed = {k for k, v in data.items() if getattr(task, k) != v}
            if task.assigned_to_id == user.id and changed <= {"status"}:
                pass  # assignee moving their own task forward
            elif not changed:
                pass  # no-op save
            else:
                raise PermissionDenied(
                    "Tasks can't be edited directly — use “Request change” and the "
                    + ("task creator" if task.created_by_id != user.id else "admin")
                    + " will approve it.")
        else:
            new_assignee = data.get("assigned_to", task.assigned_to)
            if new_assignee and new_assignee != task.assigned_to and not can_assign_to(user, new_assignee):
                raise PermissionDenied("You cannot assign to someone above your level.")

        old_assignee, old_status = task.assigned_to, task.status

        # B3: completion evidence -- enforced no matter which path marks it done
        if data.get("status") == TaskStatus.DONE and old_status != TaskStatus.DONE:
            self._enforce_completion_evidence(task)

        updated = serializer.save()
        self._after_status_change(updated, user, old_status, old_assignee, is_admin)

    def _enforce_checklist_done(self, task):
        """A task built out of steps is finished when the STEPS are finished --
        you cannot skip to the end and tick the whole thing off."""
        left = task.checklist.filter(done=False)
        n = left.count()
        if n:
            raise ValidationError({
                "detail": f"{n} step{'' if n == 1 else 's'} still open — finish the "
                          "checklist first: " + ", ".join(i.text for i in left[:3])
                          + ("…" if n > 3 else ""),
                "needs": "checklist"})

    def _enforce_completion_evidence(self, task, remarks="", has_new_file=False):
        self._enforce_checklist_done(task)
        # P2: a completion description is ALWAYS required now (reviewer's
        # rule) -- the settings toggle only governs the proof attachment.
        if not remarks:
            raise ValidationError({
                "detail": "A completion description is required — say what was done.",
                "needs": "remarks"})
        cfg = TaskSettings.get()
        if cfg.require_completion_attachment and not has_new_file and not task.attachments.exists():
            raise ValidationError({
                "detail": "A proof attachment (file/photo) is required to complete this task.",
                "needs": "attachment"})

    def _after_status_change(self, updated, user, old_status, old_assignee, was_admin_edit=False):
        if updated.status != old_status:
            act(updated, user, f"Status: {old_status} -> {updated.status}")
        if updated.status == TaskStatus.DONE and old_status != TaskStatus.DONE:
            updated.completed_at = timezone.now()
            updated.save(update_fields=["completed_at"])
            _notify_task_completed(updated, user)
            self._sync_linked_mistake(updated, user)
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
        if was_admin_edit and user.pk not in (updated.assigned_to_id, updated.created_by_id):
            act(updated, user, "Edited directly by admin")

    def _sync_linked_mistake(self, task, user):
        """A completed corrective task updates its mistake automatically
        (Sir's task-integration rule). Lazy import — mistakes imports crm."""
        from mistakes.models import Mistake
        from mistakes.views import log as mlog
        mistake = Mistake.objects.filter(corrective_task=task).select_related("manager").first()
        if not mistake:
            return
        mlog(mistake, user, f"Corrective task {task.code} completed"
             + (f": {task.completion_note[:150]}" if task.completion_note else ""))
        if mistake.manager and mistake.manager.pk != user.pk:
            notify(mistake.manager, "mistake_update",
                   f"{mistake.code}: corrective task done",
                   f"{task.code} {task.title} — review and resolve the mistake.",
                   link="/mistakes")

    def perform_destroy(self, instance):
        """A4: admin-only, and SOFT -- the task lands in the Deleted bin."""
        if not has_capability(self.request.user, "tasks.view_all"):
            raise PermissionDenied("Only an admin can delete a task.")
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])
        act(instance, self.request.user, "Moved to Deleted Tasks")

    @action(detail=True, methods=["post"], permission_classes=[HasCapability.of("tasks.view_all")])
    def restore(self, request, pk=None):
        task = Task.objects.filter(pk=pk, deleted_at__isnull=False).first()
        if not task:
            raise ValidationError({"detail": "This task is not in the Deleted bin."})
        task.deleted_at = None
        task.save(update_fields=["deleted_at"])
        act(task, request.user, "Restored from Deleted Tasks")
        return Response(TaskSerializer(task, context={"request": request}).data)

    def retrieve(self, request, *args, **kwargs):
        """E1: the detail slide-over gets checklist + sub-tasks inline."""
        data = super().retrieve(request, *args, **kwargs).data
        task = self.get_object()
        from .serializers import TaskChecklistItemSerializer
        data["checklist"] = TaskChecklistItemSerializer(task.checklist.all(), many=True).data
        data["subtasks"] = [
            {"id": s.id, "code": s.code, "title": s.title, "status": s.status,
             "assignee": s.assigned_to.get_full_name() or s.assigned_to.username}
            for s in task.subtasks.select_related("assigned_to").filter(deleted_at__isnull=True)
        ]
        return Response(data)

    def _can_touch_detail(self, user, task) -> bool:
        return (user.pk in (task.assigned_to_id, task.created_by_id)
                or has_capability(user, "tasks.view_all"))

    # ---- E1: checklist / comments / per-task feed ------------------------
    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        """Task Updates feed — system logs + comments for ONE task."""
        acts = self.get_object().activities.select_related("actor")[:100]
        return Response(TaskActivitySerializer(acts, many=True).data)

    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        task = self.get_object()
        text = str(request.data.get("text", "")).strip()
        if not text:
            raise ValidationError({"text": "Say something."})
        TaskActivity.objects.create(task=task, actor=request.user,
                                    text=text[:300], kind="comment")
        for target in (task.assigned_to, task.created_by):
            if target and target.is_active and target.pk != request.user.pk:
                who_c = request.user.get_full_name() or request.user.username
                notify(target, "task_comment",
                       f"Comment from {who_c} on {task.code}: {task.title}"[:200],
                       "\n".join([
                           f"Task: {task.code} - {task.title}",
                           f"Assigned to: {task.assigned_to.get_full_name() or task.assigned_to.username}"
                           if task.assigned_to else "Assigned to: -",
                           "",
                           f"{who_c} wrote:",
                           text[:300],
                           "",
                           "Open Tasks to reply.",
                       ]),
                       link=f"/tasks/{task.id}", link_label="Reply to this task",
                       wa_template=("task_comment_alert", [
                           target.get_full_name() or target.username,
                           who_c,
                           f"{task.code} - {task.title}",
                           text[:280],
                       ]))
        acts = task.activities.select_related("actor")[:100]
        return Response(TaskActivitySerializer(acts, many=True).data,
                        status=http.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def add_check(self, request, pk=None):
        task = self.get_object()
        if not self._can_touch_detail(request.user, task):
            raise PermissionDenied("Only the assignee, creator or admin can edit the checklist.")
        text = str(request.data.get("text", "")).strip()
        if not text:
            raise ValidationError({"text": "Checklist item text is required."})
        last = task.checklist.order_by("-order").first()
        TaskChecklistItem.objects.create(task=task, text=text[:200],
                                         order=(last.order + 1) if last else 0,
                                         created_by=request.user)
        from .serializers import TaskChecklistItemSerializer
        return Response(TaskChecklistItemSerializer(task.checklist.all(), many=True).data,
                        status=http.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="check/(?P<item_id>[0-9]+)")
    def check(self, request, pk=None, item_id=None):
        """Toggle one checklist item (or ?delete=true removes it)."""
        task = self.get_object()
        if not self._can_touch_detail(request.user, task):
            raise PermissionDenied("Only the assignee, creator or admin can edit the checklist.")
        item = task.checklist.filter(pk=item_id).first()
        if not item:
            raise ValidationError({"detail": "Unknown checklist item."})
        if request.query_params.get("delete") == "true":
            if item.done:
                raise ValidationError(
                    {"detail": "This step is already done — it cannot be removed."})
            if request.user.id == task.assigned_to_id                     and request.user.id != task.created_by_id                     and not has_capability(request.user, "tasks.view_all"):
                raise PermissionDenied(
                    "Only the person who set the steps can remove one.")
            item.delete()
        elif item.done:
            # un-ticking clears the note as well, so it can never go stale
            item.done, item.note, item.done_by, item.done_at = False, "", None, None
            item.save(update_fields=["done", "note", "done_by", "done_at"])
            act(task, request.user, f"Step re-opened: {item.text[:110]}")
        else:
            note = str(request.data.get("note", "")).strip()
            if len(note) < 5:
                raise ValidationError({
                    "note": "Say what you did for this step (a few words).",
                    "needs": "note"})
            item.done, item.note = True, note[:300]
            item.done_by, item.done_at = request.user, timezone.now()
            item.save(update_fields=["done", "note", "done_by", "done_at"])
            act(task, request.user, f"Step done: {item.text[:90]} - {note[:120]}")
        from .serializers import TaskChecklistItemSerializer
        return Response(TaskChecklistItemSerializer(task.checklist.all(), many=True).data)

    # ---- E3: AI layer (Claude behind AI_ENABLED, rules otherwise) --------
    @action(detail=False, methods=["post"])
    def ai_draft(self, request):
        """'Generate with AI Prompt': natural language -> title/description/
        checklist draft. Never blocks — falls back to rules."""
        prompt = str(request.data.get("prompt", "")).strip()
        if not prompt:
            raise ValidationError({"prompt": "Describe the task in your own words."})
        return Response(draft_task(prompt))

    @action(detail=False, methods=["post"])
    def proofread(self, request):
        """Spelling and grammar pass over whatever a person typed. The browser
        underlines mistakes but only offers fixes on right-click, which nobody
        finds -- this is the button they were looking for."""
        text = str(request.data.get("text", ""))
        if not text.strip():
            raise ValidationError({"text": "Nothing to check."})
        if len(text) > 4000:
            raise ValidationError({"text": "Too long to check — keep it under 4000 characters."})
        return Response(proofread(text))

    @action(detail=True, methods=["post"])
    def summarize(self, request, pk=None):
        task = self.get_object()
        return Response(summarize_task(task, list(task.activities.all()[:15])))

    # ---- extra actions ---------------------------------------------------
    @action(detail=False, methods=["get"])
    def assignees(self, request):
        """A1: only the people THIS user may assign to (level and below)."""
        users = assignable_users(request.user).order_by("first_name", "username")
        return Response(UserBriefSerializer(users, many=True).data)

    # C1 soft-warning thresholds: a full workday of pending effort, or a
    # pile of open tasks. Informs the assigner — never blocks the save.
    WORKLOAD_WARN_MINUTES = 8 * 60
    WORKLOAD_WARN_OPEN = 10

    @action(detail=False, methods=["get"])
    def workload(self, request):
        """C1/C2: one person's current pipeline — open-task count, priority
        breakdown, pending effort. Visible to anyone who could assign to
        them, their reporting manager, and dept/all viewers."""
        try:
            target_id = int(request.query_params.get("user", ""))
        except (TypeError, ValueError):
            raise ValidationError({"user": "Pass a user id."})
        target = User.objects.filter(pk=target_id, is_active=True).first()
        if not target:
            raise ValidationError({"user": "Unknown or inactive user."})
        allowed = (
            can_assign_to(request.user, target)
            or has_capability(request.user, "tasks.view_all")
            or (has_capability(request.user, "tasks.view_department")
                and target.department == request.user.department)
            or target.reporting_manager_id == request.user.id
        )
        if not allowed:
            raise PermissionDenied("You cannot view this person's workload.")

        qs = Task.objects.filter(assigned_to=target, deleted_at__isnull=True) \
                         .exclude(status=TaskStatus.DONE)
        rows = list(qs.values_list("priority", "effort_minutes", "due_at"))
        now = timezone.now()
        by_priority = Counter(p for p, _, _ in rows)
        pending_effort = sum(e for _, e, _ in rows if e)
        no_effort = sum(1 for _, e, _ in rows if not e)
        open_count = len(rows)
        return Response({
            "user": target.pk,
            "name": target.get_full_name() or target.username,
            "open_tasks": open_count,
            "overdue": sum(1 for _, _, d in rows if d and d < now),
            "priority_breakdown": {p: by_priority.get(p, 0)
                                   for p in ("urgent", "high", "normal", "low")},
            "pending_effort_minutes": pending_effort,
            "tasks_without_effort": no_effort,  # count toward load but earn 0h
            "overloaded": (pending_effort >= self.WORKLOAD_WARN_MINUTES
                           or open_count >= self.WORKLOAD_WARN_OPEN),
        })

    @action(detail=True, methods=["post"])
    def estimate(self, request, pk=None):
        """A2: the assignee's one-time counter-estimate. It never overwrites
        the assigner's effort value -- both go to the review report."""
        task = self.get_object()
        if task.assigned_to_id != request.user.id:
            raise PermissionDenied("Only the assignee can give their estimate.")
        if task.assignee_estimate_minutes is not None:
            raise ValidationError({"detail": "You already gave your estimate — it can't be changed."})
        try:
            minutes = int(request.data.get("minutes"))
            if not 1 <= minutes <= 60 * 24 * 30:
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError({"minutes": "Give your estimate in minutes (1 – 43200)."})
        task.assignee_estimate_minutes = minutes
        task.save(update_fields=["assignee_estimate_minutes"])
        assigner_view = f"{task.effort_minutes} min" if task.effort_minutes else "not set"
        act(task, request.user, f"Assignee estimate: {minutes} min (assigner said: {assigner_view})")
        return Response(TaskSerializer(task, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def progress(self, request, pk=None):
        """P1: repeatable 'In Progress — Status Update'. % work done, total
        effort spent so far, comment — each optional (but send at least one).
        Everything lands in the task's activity history."""
        task = self.get_object()
        if task.assigned_to_id != request.user.id:
            raise PermissionDenied("Only the assignee can post a status update.")
        if task.status == TaskStatus.DONE:
            raise ValidationError({"detail": "This task is already completed."})
        if task.deleted_at:
            raise ValidationError({"detail": "This task is deleted."})

        updates = []
        percent = request.data.get("percent")
        if percent not in (None, ""):
            try:
                percent = int(percent)
                if not 0 <= percent <= 100:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValidationError({"percent": "% work done must be between 0 and 100."})
            task.progress_percent = percent
            updates.append(f"{percent}% done")
        spent = request.data.get("spent_minutes")
        if spent not in (None, ""):
            try:
                spent = int(spent)
                if not 1 <= spent <= 60 * 24 * 90:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValidationError({"spent_minutes": "Effort spent must be a positive number of minutes."})
            task.actual_minutes = spent          # running total so far
            updates.append(f"{spent}m spent so far")
        comment = str(request.data.get("comment", "")).strip()
        if comment:
            updates.append(f"“{comment[:200]}”")
        if not updates:
            raise ValidationError({"detail": "Nothing to update — add a %, effort spent, or a comment."})

        old_status = task.status
        if task.status == TaskStatus.OPEN:
            task.status = TaskStatus.IN_PROGRESS
        task.save(update_fields=["progress_percent", "actual_minutes", "status"])
        act(task, request.user, "Status update: " + " · ".join(updates))
        if old_status != task.status:
            act(task, request.user, f"Status: {old_status} -> {task.status}")
        # the person who delegated it sees progress without asking
        if task.created_by_id and task.created_by_id != request.user.id \
                and task.created_by.is_active:
            who_upd = request.user.get_full_name() or request.user.username
            headline = (f"{task.progress_percent}% done"
                        if percent not in (None, "") else "status update")
            notify(task.created_by, "task_progress",
                   f"Progress on {task.code} ({headline}): {task.title}"[:200],
                   "\n".join([
                       f"Task: {task.code} - {task.title}",
                       f"Updated by: {who_upd}",
                       "",
                       "Update: " + " * ".join(updates),
                       f"Due: {timezone.localtime(task.due_at):%d %b %Y, %I:%M %p}"
                       if task.due_at else "Due: not set",
                       "",
                       "No action needed unless this looks off - open Tasks to reply.",
                   ]),
                   link=f"/tasks/{task.id}")
        return Response(TaskSerializer(task, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def time_report(self, request):
        """P3: per person over ?range= — Time Earned (assigned effort
        credited when the task completes) vs Time Spent (actual minutes the
        assignee reported). Employees see themselves; managers their
        department + reports; admin everyone."""
        user = request.user
        now = timezone.localtime()
        today = now.date()
        rng = request.query_params.get("range", "this_month")
        starts = {
            "today": today,
            "this_week": today - timedelta(days=today.weekday()),
            "this_month": today.replace(day=1),
            "this_year": today.replace(month=1, day=1),
            "all": None,
        }
        if rng not in starts:
            raise ValidationError({"range": f"Use one of: {', '.join(starts)}."})

        qs = Task.objects.filter(status=TaskStatus.DONE, deleted_at__isnull=True,
                                 completed_at__isnull=False)
        if starts[rng]:
            qs = qs.filter(completed_at__date__gte=starts[rng])
        if has_capability(user, "tasks.view_all"):
            pass
        elif has_capability(user, "tasks.view_department"):
            from django.db.models import Q as _Q
            qs = qs.filter(_Q(assigned_to__department=user.department)
                           | _Q(assigned_to__reporting_manager=user)
                           | _Q(assigned_to=user))
        else:
            qs = qs.filter(assigned_to=user)

        people = {}
        for assignee_id, name, username, effort, actual in qs.values_list(
                "assigned_to_id", "assigned_to__first_name",
                "assigned_to__username", "effort_minutes", "actual_minutes"):
            row = people.setdefault(assignee_id, {
                "user": assignee_id, "name": name or username,
                "done": 0, "time_earned_minutes": 0, "time_spent_minutes": 0,
                "no_effort_tasks": 0,
            })
            row["done"] += 1
            if effort:
                row["time_earned_minutes"] += effort
            else:
                row["no_effort_tasks"] += 1   # visible, so assigners learn
            row["time_spent_minutes"] += actual or 0
        rows = sorted(people.values(), key=lambda r: -r["time_earned_minutes"])
        return Response({"range": rng, "rows": rows})

    # D2 score weights (Sir's proposal, shown openly in the UI tooltip)
    SCORE_ON_TIME_WEIGHT = 60
    SCORE_EFFORT_WEIGHT = 40
    MULTITASK_PARALLEL = 3      # D4: a "multitask day" has >= this many active tasks

    def _report_bounds(self, p, now):
        """Presets from _range_bounds plus range=custom&start=&end= (D3)."""
        rng = p.get("range", "this_month")
        if rng == "custom":
            from datetime import date as _date
            try:
                start = _date.fromisoformat(p.get("start", ""))
                end = _date.fromisoformat(p.get("end", ""))
            except ValueError:
                raise ValidationError({"range": "Custom range needs start and end as YYYY-MM-DD."})
            if end < start:
                raise ValidationError({"range": "End date is before the start date."})
            return start, end
        return _range_bounds(rng, now)

    def _report_users(self, user, only_id=None):
        """People this viewer may see task data for: admin -> everyone,
        department viewer -> their department, and ANYONE -> their own direct
        reports (matching visible_tasks, so a lead with reports outside their
        department still sees that team). ?user= narrows to one of them."""
        from django.db.models import Q as _Q
        if has_capability(user, "tasks.view_all"):
            users = list(User.objects.filter(is_active=True))
        else:
            scope = _Q(pk=user.pk) | _Q(reporting_manager=user)
            if has_capability(user, "tasks.view_department"):
                scope |= _Q(department=user.department)
            users = list(User.objects.filter(is_active=True).filter(scope).distinct())
        if only_id:
            try:
                only_id = int(only_id)
            except (TypeError, ValueError):
                raise ValidationError({"user": "Pass a user id."})
            users = [u for u in users if u.pk == only_id]
            if not users:
                raise PermissionDenied("You cannot view this person's tasks.")
        return users

    @action(detail=False, methods=["get"])
    def people(self, request):
        """Who the "All Tasks" / Activities person-filter may list — the same
        set of people this viewer can already see tasks for."""
        users = sorted(self._report_users(request.user),
                       key=lambda u: (u.first_name or u.username).lower())
        return Response([{
            "id": u.pk,
            "name": u.get_full_name() or u.username,
            "username": u.username,
            "role": u.role,
            "role_display": u.get_role_display(),
            "department": u.department,
            "department_display": u.get_department_display(),
            "reports_to": u.reporting_manager_id,
        } for u in users])

    @action(detail=False, methods=["get"])
    def employees_report(self, request):
        """D2/D3/D4: per-person report over the range — counts, transparent
        score, time earned/assigned/spent, multitasker index. ?grain=daily
        returns the per-day view instead (completion-day crediting, D1)."""
        now = timezone.now()
        p = request.query_params
        start, end = self._report_bounds(p, now)
        users = self._report_users(request.user, only_id=p.get("user"))
        today = timezone.localtime(now).date()

        raw = Task.objects.filter(assigned_to__in=users, deleted_at__isnull=True) \
            .values("id", "assigned_to_id", "created_by_id", "status", "due_at",
                    "completed_at", "created_at", "effort_minutes", "actual_minutes",
                    "group__name")
        users_by_id = {u.pk: u for u in users}
        # tasks that exist only to correct a mistake are not scored -- the
        # mistake penalty already covers it (same rule as crm.scoring)
        from .scoring import corrective_task_ids
        corrective = corrective_task_ids([t["id"] for t in raw])
        per = {u.pk: [] for u in users}
        for t in raw:
            anchor = timezone.localtime(t["due_at"] or t["created_at"]).date()
            if start and not (start <= anchor <= end):
                continue
            per[t["assigned_to_id"]].append(t)

        if p.get("grain") == "daily":
            # D1: effort credits land on the COMPLETION day, whole
            days = {}
            for sub in per.values():
                for t in sub:
                    if t["status"] != TaskStatus.DONE or not t["completed_at"]:
                        continue
                    d = timezone.localtime(t["completed_at"]).date()
                    row = days.setdefault(d, {"date": d, "completed": 0, "in_time": 0,
                                              "delayed": 0, "time_earned_minutes": 0,
                                              "time_spent_minutes": 0})
                    row["completed"] += 1
                    late = t["due_at"] and t["completed_at"] > t["due_at"]
                    row["delayed" if late else "in_time"] += 1
                    row["time_earned_minutes"] += t["effort_minutes"] or 0
                    row["time_spent_minutes"] += t["actual_minutes"] or 0
            return Response({"rows": sorted(days.values(), key=lambda r: r["date"], reverse=True)})

        def tally(subset):
            """The six numbers every report table shows, so Monthly, Groups
            and OverDue all read the same as the Employees table."""
            c = Counter()
            for t in subset:
                if t["status"] != TaskStatus.DONE and t["due_at"] and t["due_at"] < now:
                    c["overdue"] += 1
                if t["status"] == TaskStatus.OPEN:
                    c["pending"] += 1
                elif t["status"] == TaskStatus.IN_PROGRESS:
                    c["in_progress"] += 1
                else:
                    c["completed"] += 1
                    late = (t["due_at"] and t["completed_at"]
                            and t["completed_at"] > t["due_at"])
                    c["delayed" if late else "in_time"] += 1
            done = c.get("completed", 0)
            return {"total": len(subset),
                    **{k: c.get(k, 0) for k in ("overdue", "pending", "in_progress",
                                                "completed", "in_time", "delayed")},
                    "score": round(100 * c.get("in_time", 0) / done, 1) if done else None}

        if p.get("grain") == "monthly":
            months = {}
            for sub in per.values():
                for t in sub:
                    d = timezone.localtime(t["due_at"] or t["created_at"]).date()
                    months.setdefault(d.replace(day=1), []).append(t)
            return Response({"rows": [
                {"month": m.isoformat(), "label": m.strftime("%b %Y"), **tally(sub)}
                for m, sub in sorted(months.items(), reverse=True)]})

        if p.get("grain") == "group":
            groups = {}
            for sub in per.values():
                for t in sub:
                    groups.setdefault(t["group__name"] or "No group", []).append(t)
            return Response({"rows": [
                {"group": g, **tally(sub)}
                for g, sub in sorted(groups.items(), key=lambda kv: kv[0].lower())]})

        if p.get("grain") == "overdue":
            # Who is sitting on late work, and how long the OLDEST one has been
            # late -- "4 months ago" is what starts a conversation, not the count.
            rows = []
            for uid, sub in per.items():
                late = [t for t in sub if t["status"] != TaskStatus.DONE
                        and t["due_at"] and t["due_at"] < now]
                if not late:
                    continue
                oldest = min(t["due_at"] for t in late)
                who = users_by_id[uid]
                rows.append({"user": uid, "name": who.get_full_name() or who.username,
                             "oldest_due_at": oldest,
                             "days_overdue": (now - oldest).days, **tally(sub)})
            rows.sort(key=lambda r: -r["days_overdue"])
            return Response({"rows": rows})

        name_of = {u.pk: (u.get_full_name() or u.username) for u in users}
        single = bool(p.get("user"))   # one person's profile: always emit a row
        rows = []
        for uid, sub in per.items():
            if not sub:
                if single:
                    rows.append({"user": uid, "name": name_of[uid], "total": 0,
                                 "overdue": 0, "pending": 0, "in_progress": 0,
                                 "completed": 0, "in_time": 0, "delayed": 0,
                                 "self_assigned": 0, "scored_completed": 0,
                                 "time_assigned_minutes": 0, "time_earned_minutes": 0,
                                 "time_spent_minutes": 0, "on_time_rate": None,
                                 "effort_ratio": None, "score": None,
                                 "multitask_days": 0, "multitask_on_time": None,
                                 "review": "No tasks in this range."})
                continue
            c = Counter()
            assigned = earned = spent = 0
            # Scoring counts ONLY tasks somebody else handed you: a task you
            # created for yourself earns no points, so nobody can inflate a
            # score by self-assigning easy work.
            sc_assigned = sc_earned = sc_completed = sc_in_time = 0
            intervals = []
            for t in sub:
                # not scored: your own task, or one raised to correct a mistake
                own = t["created_by_id"] == uid or t["id"] in corrective
                if own:
                    c["self_assigned"] += 1
                if t["status"] != TaskStatus.DONE and t["due_at"] and t["due_at"] < now:
                    c["overdue"] += 1
                if t["status"] == TaskStatus.OPEN:
                    c["pending"] += 1
                elif t["status"] == TaskStatus.IN_PROGRESS:
                    c["in_progress"] += 1
                else:
                    c["completed"] += 1
                    late = t["due_at"] and t["completed_at"] and t["completed_at"] > t["due_at"]
                    c["delayed" if late else "in_time"] += 1
                    earned += t["effort_minutes"] or 0
                    spent += t["actual_minutes"] or 0
                    if not own:
                        sc_completed += 1
                        sc_earned += t["effort_minutes"] or 0
                        if not late:
                            sc_in_time += 1
                assigned += t["effort_minutes"] or 0
                if not own:
                    sc_assigned += t["effort_minutes"] or 0
                s = timezone.localtime(t["created_at"]).date()
                e = timezone.localtime(t["completed_at"]).date() if t["completed_at"] else today
                intervals.append((s, e, t))

            # D4: multitask days — >= MULTITASK_PARALLEL tasks active the same day
            win_start = start or min(s for s, _, _ in intervals)
            win_end = min(end or today, today)
            n_days = min((win_end - win_start).days + 1, 92)   # capped sweep
            diff = [0] * (n_days + 1)
            for s, e, _ in intervals:
                lo = max((s - win_start).days, 0)
                hi = min((e - win_start).days, n_days - 1)
                if hi < 0 or lo >= n_days:
                    continue
                diff[lo] += 1
                diff[hi + 1] -= 1
            counts, running = [], 0
            for d in diff[:n_days]:
                running += d
                counts.append(running)
            mt_days = {win_start + timedelta(days=i)
                       for i, n in enumerate(counts) if n >= self.MULTITASK_PARALLEL}
            mt_done = mt_in_time = 0
            for _, _, t in intervals:
                if t["status"] == TaskStatus.DONE and t["completed_at"] \
                        and timezone.localtime(t["completed_at"]).date() in mt_days:
                    mt_done += 1
                    if not (t["due_at"] and t["completed_at"] > t["due_at"]):
                        mt_in_time += 1

            # Rates behind the score use the delegated tasks only — someone
            # with nothing but self-assigned work scores nothing at all.
            on_time_rate = (sc_in_time / sc_completed) if sc_completed else None
            effort_ratio = min(1.0, sc_earned / sc_assigned) if sc_assigned else None
            score = None
            if on_time_rate is not None and effort_ratio is not None:
                score = round(self.SCORE_ON_TIME_WEIGHT * on_time_rate
                              + self.SCORE_EFFORT_WEIGHT * effort_ratio, 1)
            elif on_time_rate is not None:   # no effort values set anywhere
                score = round(100 * on_time_rate, 1)

            row = {
                "user": uid, "name": name_of[uid], "total": len(sub),
                **{k: c.get(k, 0) for k in ("overdue", "pending", "in_progress",
                                            "completed", "in_time", "delayed",
                                            "self_assigned")},
                "scored_completed": sc_completed,     # delegated + finished
                "time_assigned_minutes": assigned,
                "time_earned_minutes": earned,
                "time_spent_minutes": spent,
                "on_time_rate": round(on_time_rate * 100, 1) if on_time_rate is not None else None,
                "effort_ratio": round(effort_ratio * 100, 1) if effort_ratio is not None else None,
                "score": score,
                "multitask_days": len(mt_days),
                "multitask_on_time": round(100 * mt_in_time / mt_done, 1) if mt_done else None,
            }
            row["review"] = review_sentence(row)   # E3: Sir's review categories
            rows.append(row)

        # M4: mistakes pull the score down — transparently
        from mistakes.analytics import MAX_EMPLOYEE_PENALTY, mistake_penalties
        pens = mistake_penalties([r["user"] for r in rows], start, end)
        for r in rows:
            pen = pens.get(r["user"], {"mistakes": 0, "repeats": 0, "penalty": 0, "action_rate": None})
            r["mistakes"] = pen["mistakes"]
            r["repeat_mistakes"] = pen["repeats"]
            r["mistake_penalty"] = pen["penalty"]
            r["mistake_action_rate"] = pen["action_rate"]
            r["task_score"] = r["score"]
            r["score"] = (round(max(0, r["score"] - pen["penalty"]), 1)
                          if r["score"] is not None else None)
        rows.sort(key=lambda r: (-(r["score"] or -1), r["name"]))
        return Response({
            "rows": rows,
            "formula": f"Score = {self.SCORE_ON_TIME_WEIGHT} × on-time rate + "
                       f"{self.SCORE_EFFORT_WEIGHT} × (time earned ÷ time assigned) "
                       f"− mistake penalty (low 1 · medium 3 · high 6 · critical 10, "
                       f"repeats ×2, max {MAX_EMPLOYEE_PENALTY}). "
                       f"Only tasks assigned BY SOMEONE ELSE are scored — a task "
                       f"you create for yourself, or one raised to correct a "
                       f"mistake, earns no points",
        })

    @action(detail=False, methods=["get"])
    def effort_disputes(self, request):
        """D5: tasks where the assignee's estimate diverged from the
        assigner's effort value — review-meeting ammunition."""
        from django.db.models import F
        now = timezone.now()
        p = request.query_params
        start, end = self._report_bounds(p, now)
        users = self._report_users(request.user)
        qs = (Task.objects.filter(assigned_to__in=users, deleted_at__isnull=True,
                                  effort_minutes__isnull=False,
                                  assignee_estimate_minutes__isnull=False)
              .exclude(effort_minutes=F("assignee_estimate_minutes"))
              .select_related("assigned_to", "created_by"))
        rows = []
        for t in qs:
            anchor = timezone.localtime(t.due_at or t.created_at).date()
            if start and not (start <= anchor <= end):
                continue
            rows.append({
                "id": t.id, "code": t.code, "title": t.title,
                "assignee": t.assigned_to.get_full_name() or t.assigned_to.username,
                "assigner": (t.created_by.get_full_name() or t.created_by.username)
                if t.created_by else "—",
                "effort_minutes": t.effort_minutes,
                "estimate_minutes": t.assignee_estimate_minutes,
                "actual_minutes": t.actual_minutes,
                "status": t.status,
            })
        rows.sort(key=lambda r: -abs(r["estimate_minutes"] - r["effort_minutes"]) / r["effort_minutes"])
        return Response({"rows": rows})

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """B3: complete WITH evidence (remarks and/or a proof file), used when
        Task Settings demand it. Plain status PATCH still works when nothing
        is required."""
        task = self.get_object()
        if task.assigned_to_id != request.user.id and not has_capability(request.user, "tasks.view_all"):
            raise PermissionDenied("Only the assignee can complete this task.")
        if task.status == TaskStatus.DONE:
            raise ValidationError({"detail": "This task is already completed."})
        remarks = str(request.data.get("remarks", "")).strip()
        # proof can be several files -- one photo rarely proves a whole job
        proof = request.FILES.getlist("file")[:self.MAX_PROOF_FILES]
        for f in proof:
            if f.size > self.MAX_UPLOAD_BYTES:
                raise ValidationError(
                    {"file": f"{f.name} is larger than 10 MB — compress it or share a link."})
        self._enforce_completion_evidence(task, remarks=remarks, has_new_file=bool(proof))
        # P2: the actual TOTAL effort spent is mandatory at completion --
        # it powers the Time Spent report next to Time Earned.
        try:
            actual = int(request.data.get("actual_minutes"))
            if not 1 <= actual <= 60 * 24 * 90:
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError({
                "actual_minutes": "Enter the total effort actually spent (in minutes).",
                "needs": "actual_minutes"})

        for f in proof:
            TaskAttachment.objects.create(task=task, file=f, filename=f.name[:255],
                                          uploaded_by=request.user)
        old_status = task.status
        task.status = TaskStatus.DONE
        task.completion_note = remarks[:500]
        task.actual_minutes = actual
        task.progress_percent = 100
        task.save(update_fields=["status", "completion_note", "actual_minutes", "progress_percent"])
        assigned_view = f"{task.effort_minutes}m" if task.effort_minutes else "not set"
        act(task, request.user,
            f"Completed — took {actual}m (assigned: {assigned_view}): {remarks[:180]}")
        for f in proof:
            act(task, request.user, f"Completion proof attached: {f.name[:120]}")
        self._after_status_change(task, request.user, old_status, task.assigned_to)
        return Response(TaskSerializer(task, context={"request": request}).data)

    @action(detail=True, methods=["get", "post"])
    def request_change(self, request, pk=None):
        """B2: raise a Modification Request. GET lists this task's requests."""
        task = self.get_object()
        if request.method == "GET":
            return Response(TaskChangeRequestSerializer(
                task.change_requests.select_related("requested_by", "reviewed_by", "task"),
                many=True).data)
        if has_capability(request.user, "tasks.view_all"):
            raise ValidationError({
                "detail": "You're an admin — edit the task directly, no request needed."})
        if request.user.id not in (task.assigned_to_id, task.created_by_id):
            raise PermissionDenied("Only the assignee or the creator can request changes to this task.")
        if task.deleted_at:
            raise ValidationError({"detail": "This task is deleted."})
        ser = TaskChangeRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        req = ser.save(task=task, requested_by=request.user)
        approver_side = "the task creator" if request.user.id != task.created_by_id else "an admin"
        # the activity feed gets the same friendly labels, not raw field names
        fields = ", ".join(TaskChangeRequest.FIELD_LABELS.get(f, f).lower()
                           for f in req.changes)
        act(task, request.user, f"Change requested ({fields}) — awaiting {approver_side}")
        for approver in _approvers_for(req):
            notify(approver, "task_change_request",
                   f"Change request on {task.code}: {task.title}"[:200],
                   _change_request_body(req, approver),
                   link=f"/tasks/{task.id}")
        return Response(TaskChangeRequestSerializer(req).data, status=http.HTTP_201_CREATED)

    MAX_UPLOAD_BYTES = 10 * 1024 * 1024
    MAX_PROOF_FILES = 5

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def upload(self, request, pk=None):
        """Attach a reference file to a task -- the invoice or photo the
        assignee needs in order to DO the work. (Completion proof goes up the
        same way through /complete/.)"""
        task = self.get_object()
        if not self._can_touch_detail(request.user, task):
            raise PermissionDenied(
                "Only the assignee, the person who gave the task, or an admin "
                "can add files here.")
        if task.deleted_at:
            raise ValidationError({"detail": "This task is deleted."})
        uploaded = request.FILES.getlist("file") or (
            [request.FILES["files"]] if "files" in request.FILES else [])
        if not uploaded:
            raise ValidationError({"file": "Pick a file to attach."})
        for f in uploaded[:5]:
            if f.size > self.MAX_UPLOAD_BYTES:
                raise ValidationError(
                    {"file": f"{f.name} is larger than 10 MB — compress it or share a link."})
        for f in uploaded[:5]:
            TaskAttachment.objects.create(task=task, file=f, filename=f.name[:255],
                                          uploaded_by=request.user)
            act(task, request.user, f"Attached: {f.name[:120]}")
        return Response(TaskAttachmentSerializer(
            task.attachments.select_related("uploaded_by"), many=True).data,
            status=http.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def files(self, request, pk=None):
        task = self.get_object()
        return Response(TaskAttachmentSerializer(
            task.attachments.select_related("uploaded_by"), many=True).data)

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

        start, end = self._report_bounds(p, now) if p.get("range") == "custom" \
            else _range_bounds(p.get("range", "this_week"), now)
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
        # Say which dates were actually counted. "This week" often straddles
        # two months (a Monday in August, a Thursday in September), so a task
        # can sit in This Week and not in This Month -- correct, and baffling
        # until you can see the dates.
        return Response({
            "tiles": {**tally(rows), "total": len(rows)},
            "categories": categories,
            "range_from": start.isoformat() if start else None,
            "range_to": end.isoformat() if end else None,
        })


class TaskChangeRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """Modification Requests. Scopes:
      ?scope=inbox  -> requests waiting for ME to approve (default)
      ?scope=mine   -> requests I raised
      ?scope=all    -> everything (admin only)
    POST /{id}/review {decision: approved|rejected, remarks} applies it."""
    permission_classes = [IsAuthenticated]
    serializer_class = TaskChangeRequestSerializer

    def get_queryset(self):
        user = self.request.user
        qs = TaskChangeRequest.objects.select_related(
            "task", "task__assigned_to", "task__created_by", "requested_by", "reviewed_by")
        scope = self.request.query_params.get("scope", "inbox")
        if scope == "mine":
            qs = qs.filter(requested_by=user)
        elif scope == "all":
            if not has_capability(user, "tasks.view_all"):
                raise PermissionDenied("Only an admin can see all change requests.")
        else:  # inbox — only what THIS person is actually meant to decide
            creator_raised = Q(requested_by=F("task__created_by"))
            # a task I gave out, someone else is asking to change it
            i_gave_it = Q(task__created_by=user)
            # my own report asking to change a task they created themselves
            from_my_report = Q(requested_by__reporting_manager=user) & creator_raised
            if has_capability(user, "tasks.view_all"):
                # admins are the LAST resort, not the default inbox: only
                # escalations and people with no manager on file land here
                no_manager = (Q(requested_by__reporting_manager__isnull=True)
                              | Q(requested_by__reporting_manager__is_active=False))
                qs = qs.filter(i_gave_it | from_my_report | Q(escalated=True)
                               | (creator_raised & no_manager))
            else:
                qs = qs.filter(i_gave_it | from_my_report).filter(escalated=False)
            qs = qs.exclude(requested_by=user).filter(status=ChangeRequestStatus.PENDING)
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        req = TaskChangeRequest.objects.select_related("task", "requested_by").filter(pk=pk).first()
        if not req:
            raise ValidationError({"detail": "Unknown request."})
        if not can_review_request(request.user, req):
            raise PermissionDenied(
                "You cannot review this request"
                + (" — never your own." if req.requested_by_id == request.user.id else "."))
        if req.status != ChangeRequestStatus.PENDING:
            raise ValidationError({"detail": "This request has already been reviewed."})
        decision = request.data.get("decision")
        if decision not in ("approved", "rejected", "escalated"):
            raise ValidationError({"decision": "Use 'approved', 'rejected' or 'escalated'."})

        # B9: the creator can hand the decision up to admin instead of deciding
        if decision == "escalated":
            if has_capability(request.user, "tasks.view_all"):
                raise ValidationError({"decision": "You're the final approver — approve or reject."})
            req.escalated = True
            req.remarks = str(request.data.get("remarks", ""))[:300]
            req.save(update_fields=["escalated", "remarks"])
            act(req.task, request.user,
                f"Change request escalated to admin by {request.user.get_full_name() or request.user.username}")
            for admin in _admins().exclude(pk=req.requested_by_id):
                notify(admin, "task_change_request",
                       f"Escalated to you - change request on {req.task.code}: {req.task.title}"[:200],
                       _change_request_body(req, admin)
                       + f"\nEscalated by: {request.user.get_full_name() or request.user.username}"
                       + (f"\nTheir remarks: {req.remarks}" if req.remarks else ""),
                       link=f"/tasks/{req.task.id}")
            notify(req.requested_by, "task_change_reviewed",
                   f"Sent to admin - your change request on {req.task.code}: {req.task.title}"[:200],
                   "\n".join([
                       f"Task: {req.task.code} - {req.task.title}",
                       f"Passed up by: {request.user.get_full_name() or request.user.username}",
                       "", "You asked to change:",
                   ] + [f"  - {line}" for line in req.describe()]
                     + ([f"\nTheir remarks: {req.remarks}"] if req.remarks else [])
                     + ["", "An admin will decide this now - nothing to do until then."]),
                   link=f"/tasks/{req.task.id}")
            return Response(TaskChangeRequestSerializer(req).data)

        req.status = decision
        req.reviewed_by = request.user
        req.remarks = str(request.data.get("remarks", ""))[:300]
        req.reviewed_at = timezone.now()
        req.save()

        task = req.task
        if decision == "approved":
            applied = self._apply(task, req.changes, request.user)
            act(task, request.user,
                f"Change request approved ({', '.join(applied)}) — requested by "
                f"{req.requested_by.get_full_name() or req.requested_by.username}")
        else:
            act(task, request.user, "Change request rejected"
                + (f": {req.remarks}" if req.remarks else ""))

        verdict = "approved" if decision == "approved" else "rejected"
        notify(req.requested_by, "task_change_reviewed",
               f"Change request {verdict} - {task.code}: {task.title}"[:200],
               "\n".join([
                   f"Task: {task.code} - {task.title}",
                   f"Reviewed by: {request.user.get_full_name() or request.user.username}",
                   "",
                   ("These changes are now live on the task:" if decision == "approved"
                    else "These changes were NOT applied - the task is unchanged:"),
               ] + [f"  - {line}" for line in req.describe()]
                 + ([f"\nRemarks: {req.remarks}"] if req.remarks else [])
                 + ["", ("Nothing to do - carry on with the task."
                         if decision == "approved"
                         else "Talk to the reviewer if you still need this change.")]),
               link=f"/tasks/{task.id}")
        # keep Admin in the loop on creator-approved requests too
        if not has_capability(request.user, "tasks.view_all"):
            for admin in _admins().exclude(pk__in=[request.user.pk, req.requested_by_id]):
                notify(admin, "task_change_log",
                       f"FYI - {task.code} changed via request ({verdict}): {task.title}"[:200],
                       "\n".join([
                           f"Task: {task.code} - {task.title}",
                           f"Assigned to: {task.assigned_to.get_full_name() or task.assigned_to.username}"
                           if task.assigned_to else "Assigned to: -",
                           f"Requested by: {req.requested_by.get_full_name() or req.requested_by.username}",
                           f"{verdict.title()} by: {request.user.get_full_name() or request.user.username}",
                           "", "Changes:",
                       ] + [f"  - {line}" for line in req.describe()]
                         + ["", "Log only - no action needed."]),
                       link=f"/tasks/{task.id}")
        return Response(TaskChangeRequestSerializer(req).data)

    def _apply(self, task, changes, actor):
        """Apply an approved request's changes to the task, safely."""
        from datetime import datetime
        applied = []
        if changes.get("cancel"):
            task.deleted_at = timezone.now()
            task.save(update_fields=["deleted_at"])
            return ["cancelled (moved to Deleted Tasks)"]
        for field in ("title", "description", "category", "priority", "frequency"):
            if field in changes and changes[field] is not None:
                setattr(task, field, str(changes[field])[:200 if field == "title" else 2000])
                applied.append(field)
        if "effort_minutes" in changes:
            value = changes["effort_minutes"]
            task.effort_minutes = int(value) if value is not None else None
            applied.append("effort_minutes")
        if "due_at" in changes:
            value = changes["due_at"]
            if value:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed)
                task.due_at = parsed
                # a moved deadline deserves a fresh reminder
                task.reminded_at = None
            else:
                task.due_at = None
            applied.append("due_at")
        if "repeat_until" in changes:
            value = changes["repeat_until"]
            task.repeat_until = (datetime.fromisoformat(str(value)).date() if value else None)
            applied.append("repeat_until")
        if "assigned_to" in changes:
            target = User.objects.filter(pk=changes["assigned_to"], is_active=True).first()
            if target:
                task.assigned_to = target
                applied.append(f"assigned_to -> {target.username}")
                _notify_task_assigned(task, actor)
        task.save()
        return applied


class TaskCategoryViewSet(viewsets.ModelViewSet):
    """Managed categories: everyone reads (filtered by ?department=),
    managers/admin create and deactivate."""
    serializer_class = None  # set below via get_serializer_class
    pagination_class = None

    def get_serializer_class(self):
        from .serializers import TaskCategorySerializer
        return TaskCategorySerializer

    def get_permissions(self):
        # NOTE: this override replaces the @action permission_classes, so the
        # approve/reject actions must be listed here explicitly.
        if getattr(self, "action", None) in ("approve", "reject"):
            return [HasCapability.of("tasks.assign")()]
        # POST is otherwise open to everyone: managers/admin add outright, an
        # employee's POST becomes a request instead (handled in create()).
        if self.request.method in ("GET", "HEAD", "OPTIONS", "POST"):
            return [IsAuthenticated()]
        return [HasCapability.of("tasks.assign")()]

    def get_queryset(self):
        from django.db.models import Q as _Q
        if self.request.query_params.get("pending") == "true":
            if not has_capability(self.request.user, "tasks.assign"):
                return TaskCategory.objects.none()
            return TaskCategory.objects.filter(pending=True).select_related("requested_by")
        qs = TaskCategory.objects.filter(active=True, pending=False)
        department = self.request.query_params.get("department")
        if department is not None:
            qs = qs.filter(_Q(department="") | _Q(department=department))
        return qs

    @action(detail=True, methods=["post"],
            permission_classes=[HasCapability.of("tasks.assign")])
    def approve(self, request, pk=None):
        """Turn an employee's request into a real category."""
        cat = TaskCategory.objects.filter(pk=pk, pending=True).first()
        if not cat:
            raise ValidationError({"detail": "No pending request with that id."})
        cat.pending, cat.active = False, True
        cat.created_by = request.user
        cat.save(update_fields=["pending", "active", "created_by"])
        if cat.requested_by and cat.requested_by.is_active:
            notify(cat.requested_by, "category_request",
                   f"Category approved: {cat.name}"[:200],
                   NL_JOIN([
                       f"Category: {cat.name}",
                       f"Approved by: {request.user.get_full_name() or request.user.username}",
                       "",
                       "It is now in the category dropdown — you can pick it on any task.",
                   ]), link="/tasks")
        return Response(self.get_serializer(cat).data)

    @action(detail=True, methods=["post"],
            permission_classes=[HasCapability.of("tasks.assign")])
    def reject(self, request, pk=None):
        cat = TaskCategory.objects.filter(pk=pk, pending=True).first()
        if not cat:
            raise ValidationError({"detail": "No pending request with that id."})
        name, asker = cat.name, cat.requested_by
        remarks = str(request.data.get("remarks", "")).strip()
        cat.delete()
        if asker and asker.is_active:
            notify(asker, "category_request",
                   f"Category not added: {name}"[:200],
                   NL_JOIN([
                       f"Category: {name}",
                       f"Reviewed by: {request.user.get_full_name() or request.user.username}",
                       "",
                       "This was not added to the list."
                   ] + ([f"Reason: {remarks}"] if remarks else [])
                     + ["", "Pick the closest existing category, or ask your manager."]),
                   link="/tasks")
        return Response({"detail": "Request rejected."})

    def list(self, request, *args, **kwargs):
        """F1: ?counts=true adds live task counts per category (admin list)."""
        res = super().list(request, *args, **kwargs)
        if request.query_params.get("counts") == "true":
            counts = Counter(c.lower() for c in Task.objects
                             .filter(deleted_at__isnull=True).exclude(category="")
                             .values_list("category", flat=True))
            for row in res.data:
                row["task_count"] = counts.get(row["name"].lower(), 0)
        return res

    def create(self, request, *args, **kwargs):
        # re-adding a deactivated category reactivates it instead of
        # tripping the (department, name) unique constraint
        name = (request.data.get("name") or "").strip()
        department = request.data.get("department") or ""
        existing = TaskCategory.objects.filter(
            name__iexact=name, department=department).first()
        if existing and not existing.active:
            if not has_capability(request.user, "tasks.assign"):
                # an employee cannot silently revive a category a manager hid
                if existing.pending:
                    raise ValidationError(
                        {"name": "This category has already been requested — "
                                 "your manager still has to approve it."})
                raise ValidationError(
                    {"name": "That category was removed. Ask your manager to bring it back."})
            existing.active, existing.pending = True, False
            existing.save(update_fields=["active", "pending"])
            return Response(self.get_serializer(existing).data, status=http.HTTP_201_CREATED)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        """Managers and admin add straight away; anyone else raises a request
        that lands in Settings for a manager to approve."""
        user = self.request.user
        if has_capability(user, "tasks.assign"):
            serializer.save(created_by=user, active=True, pending=False)
            return
        cat = serializer.save(requested_by=user, active=False, pending=True)
        for approver in _category_approvers(user):
            notify(approver, "category_request",
                   f"Category requested by {user.get_full_name() or user.username}: {cat.name}"[:200],
                   NL_JOIN([
                       f"Requested category: {cat.name}",
                       f"For department: {cat.get_department_display() or 'All departments'}",
                       f"Asked by: {user.get_full_name() or user.username}",
                       "",
                       "They could not find a category that fits their task.",
                       "Approve or reject it in Settings -> Task categories.",
                   ]), link="/settings", link_label="Review the request")

    def perform_destroy(self, instance):
        instance.active = False              # never lose reporting history
        instance.pending = False
        instance.save(update_fields=["active", "pending"])


class TaskSettingsView(viewsets.ViewSet):
    """GET: anyone (the UI needs to know if evidence is required).
    PUT: admin only."""
    permission_classes = [IsAuthenticated]

    def list(self, request):
        return Response(TaskSettingsSerializer(TaskSettings.get()).data)

    def create(self, request):   # POST /api/task-settings/
        if not has_capability(request.user, "settings.manage"):
            raise PermissionDenied("Only an admin can change task policies.")
        cfg = TaskSettings.get()
        ser = TaskSettingsSerializer(cfg, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save(updated_by=request.user)
        return Response(ser.data)


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
        qs = TaskActivity.objects.select_related("actor", "task", "task__assigned_to").filter(
            task__in=visible_tasks(self.request.user))
        p = self.request.query_params
        if p.get("actor"):
            qs = qs.filter(actor_id=p["actor"])
        if p.get("assigned_to"):
            # whose TASK the activity belongs to (vs. who performed it)
            qs = qs.filter(task__assigned_to_id=p["assigned_to"])
        if p.get("department"):
            qs = qs.filter(task__assigned_to__department=p["department"])
        if p.get("task"):
            qs = qs.filter(task_id=p["task"])
        if p.get("kind"):
            qs = qs.filter(kind=p["kind"])
        if p.get("search"):
            from django.db.models import Q as _Q
            term = p["search"].strip()
            clause = _Q(text__icontains=term) | _Q(task__title__icontains=term)
            digits = term.lstrip("Tt-").lstrip("0")   # T-00042 -> task pk
            if digits.isdigit():
                clause |= _Q(task_id=int(digits))
            qs = qs.filter(clause)
        if p.get("days"):
            try:
                qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=int(p["days"])))
            except ValueError:
                pass
        return qs


    @action(detail=False, methods=["get"])
    def counts(self, request):
        """Who has been active, and how much — the chips above the feed.
        Uses exactly the same filters as the list, so the numbers always
        match what the feed below is showing."""
        rows = (self.filter_queryset(self.get_queryset())
                .values("actor_id", "actor__first_name", "actor__last_name",
                        "actor__username")
                .annotate(n=Count("id")).order_by("-n")[:25])
        return Response([{
            "user": r["actor_id"],
            "name": (f"{r['actor__first_name'] or ''} {r['actor__last_name'] or ''}".strip()
                     or r["actor__username"] or "System"),
            "count": r["n"],
        } for r in rows if r["actor_id"]])


class HolidayViewSet(viewsets.ModelViewSet):
    """Company holiday calendar: everyone reads, admin manages."""
    serializer_class = HolidaySerializer
    queryset = Holiday.objects.all()
    pagination_class = None

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [HasCapability.of("settings.manage")()]
