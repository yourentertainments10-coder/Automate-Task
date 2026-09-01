"""Mistake Register APIs.

Visibility: employees see their own record; managers see their department +
direct reports; admin sees everything. The founder-level view is a filter
(?important=true), not another system.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import status as http, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import HasCapability, has_capability
from notifications.service import notify

from .models import (
    SOP, Classification, Level3Action, Mistake, MistakeCategory, MistakeEvent,
    MistakeSettings, MistakeStatus, RootCause, Severity,
)
from .serializers import (
    MistakeCategorySerializer, MistakeEventSerializer, MistakeSerializer,
    MistakeSettingsSerializer, SOPSerializer,
)


def NL(lines):
    """Join notification body lines."""
    return chr(10).join(lines)


def log(mistake, actor, text):
    MistakeEvent.objects.create(mistake=mistake, actor=actor, text=text[:400])


def _admins():
    from accounts.permissions import ROLE_CAPABILITIES
    roles = [r for r, caps in ROLE_CAPABILITIES.items() if "tasks.view_all" in caps]
    return User.objects.filter(is_active=True, role__in=roles)


def _escalation_target(mistake, level):
    """0 = accountable manager, 1 = the manager's own manager (dept head),
    2 = founder/admin. Falls through to admins when the chain runs out."""
    if level == 0 and mistake.manager:
        return [mistake.manager]
    if level == 1 and mistake.manager and mistake.manager.reporting_manager \
            and mistake.manager.reporting_manager.is_active:
        return [mistake.manager.reporting_manager]
    return list(_admins())


def can_review(user, mistake) -> bool:
    if has_capability(user, "tasks.view_all"):
        return True
    if user.pk == mistake.employee_id:
        return False        # never your own review
    if mistake.manager_id == user.pk:
        return True
    return (has_capability(user, "tasks.view_department")
            and mistake.department == user.department)


class MistakeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = MistakeSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = Mistake.objects.select_related(
            "employee", "manager", "reported_by", "repeat_of", "task", "corrective_task")
        if has_capability(user, "tasks.view_all"):
            pass
        elif has_capability(user, "tasks.view_department"):
            qs = qs.filter(Q(department=user.department)
                           | Q(employee__reporting_manager=user)
                           | Q(employee=user) | Q(reported_by=user)).distinct()
        else:
            qs = qs.filter(Q(employee=user) | Q(reported_by=user)).distinct()

        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("severity"):
            qs = qs.filter(severity=p["severity"])
        if p.get("employee"):
            qs = qs.filter(employee_id=p["employee"])
        if p.get("category"):
            qs = qs.filter(category__iexact=p["category"])
        if p.get("important") == "true":
            # the founder view: critical/high, escalated, overdue, level 3
            qs = qs.filter(
                Q(severity__in=[Severity.HIGH, Severity.CRITICAL])
                | Q(escalation_level__gte=1) | Q(occurrence_level__gte=3)
                | Q(sla_due_at__lt=timezone.now()) & ~Q(status=MistakeStatus.RESOLVED))
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        employee = serializer.validated_data["employee"]
        if employee.pk != user.pk and not has_capability(user, "tasks.assign"):
            raise PermissionDenied("Only managers/admin can log a mistake for someone else.")
        name = (serializer.validated_data.get("category") or "").strip()
        cat = MistakeCategory.objects.filter(active=True, name__iexact=name).first()
        if not cat:
            raise ValidationError({"category": "Pick a category from the list."})

        mistake = serializer.save(
            category=cat.name, reported_by=user,
            department=employee.department,
            manager=employee.reporting_manager if employee.reporting_manager
            and employee.reporting_manager.is_active else None,
        )
        mistake.set_sla()
        mistake.save(update_fields=["sla_due_at"])
        log(mistake, user, f"Logged: {mistake.category} · severity {mistake.severity}"
            + (f" · ₹{mistake.financial_loss} loss" if mistake.financial_loss else ""))
        self._apply_repeat_rules(mistake, user)

        # LEVEL 1: employee is asked to explain + correct (with SOP reference)
        if employee.pk != user.pk:
            notify(employee, "mistake_logged",
                   f"{mistake.code} · {mistake.category} — your explanation is needed",
                   f"{mistake.description[:300]}\n\nPlease add your explanation, "
                   "the root cause and your corrective action."
                   + (f"\nSOP: {mistake.sop_name}" if mistake.sop_name else ""),
                   link="/mistakes")
        if mistake.manager and mistake.manager.pk != user.pk:
            notify(mistake.manager, "mistake_logged",
                   f"{mistake.code} logged for {employee.get_full_name() or employee.username}",
                   f"{mistake.category} · {mistake.get_severity_display()} — you own the correction.",
                   link="/mistakes")
        # founder sees HIGH/CRITICAL immediately — nothing else
        if mistake.severity in (Severity.HIGH, Severity.CRITICAL):
            for admin in _admins().exclude(pk=user.pk):
                notify(admin, "mistake_logged",
                       f"{mistake.get_severity_display().upper()}: {mistake.code} {mistake.category}",
                       f"{employee.get_full_name() or employee.username} ({mistake.get_department_display() or '—'})"
                       f" — {mistake.description[:200]}", link="/mistakes")

    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        data = super().retrieve(request, *args, **kwargs).data
        mistake = self.get_object()
        # smart-repeat candidates: same employee + same category, unconfirmed
        if can_review(request.user, mistake) and not mistake.repeat_of:
            data["possible_repeats"] = [
                {"id": m.id, "code": m.code, "description": m.description[:150],
                 "occurrence_level": m.occurrence_level,
                 "created_at": m.created_at}
                for m in Mistake.objects.filter(
                    employee=mistake.employee, category__iexact=mistake.category,
                    created_at__gte=timezone.now() - timedelta(days=365))
                .exclude(pk=mistake.pk).order_by("-created_at")[:5]
            ]
        return Response(data)

    # ---- rules: counting, escalation, the corrective task ----------------
    def _apply_repeat_rules(self, mistake, actor):
        """Everything with a consequence is decided by counting, never by a
        model: the occurrence number, whether training is due, whether a PIP
        should be proposed, and the corrective task itself."""
        from crm.models import Task
        from . import intelligence as intel

        count = intel.occurrence_count(mistake)
        verdict = intel.escalation_for(count)
        prior = intel.prior_mistakes(mistake).first()

        if count > 1:
            # the SUGGESTION is automatic; a manager still confirms the link
            mistake.occurrence_level = min(count, 3)
            if prior and not mistake.repeat_of_id:
                mistake.repeat_of = prior
            mistake.escalation_level = max(mistake.escalation_level,
                                           1 if verdict["suggest_pip"] else 0)
            mistake.save(update_fields=["occurrence_level", "repeat_of",
                                        "escalation_level"])
            log(mistake, actor,
                f"Occurrence {count} of '{mistake.category}' for this person "
                f"\u2014 {verdict['why']}")

        # the corrective task, spawned from the log itself
        if mistake.employee and mistake.employee.is_active and not mistake.corrective_task_id:
            due = timezone.now() + timedelta(days=2)
            task = Task.objects.create(
                title=f"Correct: {mistake.description[:80]}",
                description=(f"Raised from mistake {mistake.code} "
                             f"({mistake.category}).\n\n{mistake.description[:600]}\n\n"
                             "Fix this, then explain the root cause on the mistake."),
                assigned_to=mistake.employee,
                created_by=actor if actor != mistake.employee else (mistake.manager or actor),
                department=mistake.department or "",
                category=mistake.category or "",
                priority="high" if count >= intel.TRAINING_AT else "normal",
                effort_minutes=30, due_at=due,
            )
            mistake.corrective_task = task
            mistake.save(update_fields=["corrective_task"])
            log(mistake, actor, f"Corrective task {task.code} created automatically")
            notify(mistake.employee, "mistake_logged",
                   f"Correct {mistake.code}: {mistake.description[:120]}"[:200],
                   NL([f"Mistake: {mistake.code} \u00b7 {mistake.category}",
                       mistake.description[:400], "",
                       f"A corrective task {task.code} has been created for you.",
                       "Fix it, then explain the root cause on the mistake."]),
                   link=f"/tasks/{task.id}", link_label="Open the corrective task")

        # training / PIP prompt to the accountable manager
        if verdict["needs_training"] and mistake.manager and mistake.manager.is_active:
            who = mistake.employee.get_full_name() or mistake.employee.username
            head = (f"{who} has repeated '{mistake.category}' {count} times"
                    if not verdict["suggest_pip"]
                    else f"PIP review due: {who}, {count} times on '{mistake.category}'")
            notify(mistake.manager, "mistake_repeat", head[:200],
                   NL([f"Person: {who}",
                       f"Category: {mistake.category}",
                       f"Occurrence: {count} (counted over the last 12 months)",
                       "",
                       verdict["why"],
                       "",
                       ("Run a training session on this and record it, or the same "
                        "mistake will keep coming back."
                        if not verdict["suggest_pip"] else
                        "Coaching has not closed this. Consider a formal Performance "
                        "Improvement Plan \u2014 the decision is yours, the system only "
                        "counts."),
                       "",
                       "This is a count, not a judgement: "
                       f"{count} entries in the same category in 12 months."]),
                   link="/mistakes")

    # ---- AI: suggestions a human accepts or overrides ---------------------
    @action(detail=True, methods=["get"])
    def suggestions(self, request, pk=None):
        """Everything the AI has to offer on one mistake, in one call.

        Nothing here is applied automatically. Each block says which provider
        produced it, and is null when the AI is off or unreachable \u2014 the
        register keeps working either way.
        """
        from . import intelligence as intel
        mistake = self.get_object()
        allowed = list(MistakeCategory.objects.filter(active=True)
                       .values_list("name", flat=True))
        count = intel.occurrence_count(mistake)
        return Response({
            "occurrence": count,
            "escalation": intel.escalation_for(count),
            "category": intel.suggest_category(mistake.description, allowed),
            "similar": intel.similar_past_mistakes(mistake),
            "capa": intel.suggest_capa(mistake, count),
            "judgement": intel.judge_human_or_process(mistake),
        })

    # ---- employee's side ------------------------------------------------
    @action(detail=True, methods=["post"])
    def explain(self, request, pk=None):
        """Employee's structured response: explanation + root cause (from the
        fixed list — 'mistake happened' is not an explanation) + actions."""
        mistake = self.get_object()
        if mistake.employee_id != request.user.id:
            raise PermissionDenied("Only the employee involved can explain this mistake.")
        if mistake.status == MistakeStatus.RESOLVED:
            raise ValidationError({"detail": "This mistake is already resolved."})
        explanation = str(request.data.get("explanation", "")).strip()
        root_cause = request.data.get("root_cause", "")
        if not explanation:
            raise ValidationError({"explanation": "Explain what happened."})
        if root_cause not in RootCause.values:
            raise ValidationError({"root_cause": "Pick a root cause from the list."})
        mistake.explanation = explanation[:2000]
        mistake.root_cause = root_cause
        mistake.root_cause_note = str(request.data.get("root_cause_note", ""))[:500]
        mistake.corrective_action = str(request.data.get("corrective_action", ""))[:1000]
        # level >= 2: corrective AND preventive action are mandatory
        mistake.preventive_action = str(request.data.get("preventive_action", ""))[:1000]
        if mistake.occurrence_level >= 2:
            if not mistake.corrective_action or not mistake.preventive_action:
                raise ValidationError({
                    "detail": "REPEAT ERROR: both corrective AND preventive action are required."})
        mistake.status = MistakeStatus.EXPLAINED
        mistake.save()
        log(mistake, request.user,
            f"Explained · root cause: {mistake.get_root_cause_display()}")
        if mistake.manager:
            notify(mistake.manager, "mistake_update",
                   f"{mistake.code} — {request.user.get_full_name() or request.user.username} responded",
                   f"Root cause: {mistake.get_root_cause_display()}\n{explanation[:200]}",
                   link="/mistakes")
        return Response(MistakeSerializer(mistake).data)

    # ---- manager's side -------------------------------------------------
    @action(detail=True, methods=["post"])
    def confirm_repeat(self, request, pk=None):
        """Manager decides 'Same Error' / 'Different Error' against a prior
        mistake — the system suggests, a human confirms (per spec)."""
        mistake = self.get_object()
        if not can_review(request.user, mistake):
            raise PermissionDenied("Only the accountable manager or admin can classify repeats.")
        if request.data.get("same") is not True:
            log(mistake, request.user, "Classified as a DIFFERENT error (not a repeat)")
            return Response(MistakeSerializer(mistake).data)
        prior = Mistake.objects.filter(pk=request.data.get("repeat_of"),
                                       employee=mistake.employee).first()
        if not prior or prior.pk == mistake.pk:
            raise ValidationError({"repeat_of": "Pick one of this employee's earlier mistakes."})
        mistake.repeat_of = prior
        mistake.occurrence_level = min(prior.occurrence_level + 1, 3)
        mistake.save(update_fields=["repeat_of", "occurrence_level"])

        if mistake.occurrence_level == 2:
            log(mistake, request.user, f"REPEAT ERROR DETECTED (2nd occurrence, prior: {prior.code}) "
                "— root cause + corrective + preventive action now mandatory; manager accountable")
            if mistake.manager:
                notify(mistake.manager, "mistake_repeat",
                       f"REPEAT ERROR: {mistake.code} ({mistake.category})",
                       f"{mistake.employee.get_full_name() or mistake.employee.username} repeated "
                       f"{prior.code}. You are accountable for the resolution.", link="/mistakes")
            notify(mistake.employee, "mistake_repeat",
                   f"REPEAT ERROR DETECTED: {mistake.code}",
                   "This mistake was made before. Root cause, corrective AND "
                   "preventive action are now required.", link="/mistakes")
        else:  # level 3
            mistake.escalation_level = max(mistake.escalation_level, 1)
            mistake.save(update_fields=["escalation_level"])
            log(mistake, request.user,
                f"THIRD OCCURRENCE — PERFORMANCE ESCALATION (prior: {prior.code}); "
                "department head action required")
            for target in _escalation_target(mistake, 1):
                notify(target, "mistake_escalated",
                       f"THIRD OCCURRENCE: {mistake.code} — {mistake.employee.get_full_name() or mistake.employee.username}",
                       f"{mistake.category} repeated a 3rd time. Department-head action "
                       "required (coaching / retraining / warning / PIP / process change…).",
                       link="/mistakes")
        return Response(MistakeSerializer(mistake).data)

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        """Manager review — remarks, classification (never auto-blame),
        SOP verdicts, optional level-3 action, resolve. Managers cannot just
        click Close: resolving needs remarks + a classification."""
        mistake = self.get_object()
        if not can_review(request.user, mistake):
            raise PermissionDenied("Only the accountable manager or admin can review this.")
        data = request.data

        if data.get("classification"):
            if data["classification"] not in Classification.values:
                raise ValidationError({"classification": "Unknown classification."})
            mistake.classification = data["classification"]
        if data.get("severity"):
            if data["severity"] not in Severity.values:
                raise ValidationError({"severity": "Unknown severity."})
            if data["severity"] != mistake.severity:
                log(mistake, request.user, f"Severity: {mistake.severity} -> {data['severity']}")
                mistake.severity = data["severity"]
                mistake.set_sla()
        for field in ("sop_name", "sop_version", "sop_step"):
            if field in data:
                setattr(mistake, field, str(data[field])[:200])
        for field in ("sop_followed", "sop_adequate"):
            if field in data and data[field] is not None:
                setattr(mistake, field, bool(data[field]))
        if data.get("level3_action"):
            if mistake.occurrence_level < 3:
                raise ValidationError({"level3_action": "Level-3 actions apply only to third occurrences."})
            if data["level3_action"] not in Level3Action.values:
                raise ValidationError({"level3_action": "Unknown action."})
            mistake.level3_action = data["level3_action"]
            mistake.level3_action_note = str(data.get("level3_action_note", ""))[:500]
            log(mistake, request.user,
                f"Level-3 action decided by {request.user.get_full_name() or request.user.username}: "
                f"{mistake.get_level3_action_display()}")
        if "manager_remarks" in data:
            mistake.manager_remarks = str(data["manager_remarks"])[:1000]

        if data.get("resolve"):
            if not mistake.manager_remarks:
                raise ValidationError({"manager_remarks": "Say what was decided — a review is not just a click."})
            if not mistake.classification:
                raise ValidationError({"classification":
                    "Classify it first: human / process / system / management / external."})
            if mistake.occurrence_level >= 3 and not mistake.level3_action:
                raise ValidationError({"level3_action":
                    "A third occurrence needs a decided action before closing."})
            mistake.status = MistakeStatus.RESOLVED
            mistake.resolved_at = timezone.now()
            log(mistake, request.user, "Resolved"
                + (f" · SOP adequate: {'yes' if mistake.sop_adequate else 'NO — process fix needed'}"
                   if mistake.sop_adequate is not None else ""))
            notify(mistake.employee, "mistake_update",
                   f"{mistake.code} resolved", mistake.manager_remarks[:300], link="/mistakes")
        mistake.save()
        return Response(MistakeSerializer(mistake).data)

    @action(detail=True, methods=["post"])
    def create_task(self, request, pk=None):
        """Task integration: spawn the corrective/audit task, linked back."""
        from crm.models import Task
        from crm.scoping import can_assign_to
        mistake = self.get_object()
        if not can_review(request.user, mistake):
            raise PermissionDenied("Only the accountable manager or admin can create the corrective task.")
        if mistake.corrective_task:
            raise ValidationError({"detail": f"Corrective task {mistake.corrective_task.code} already exists."})
        assignee = User.objects.filter(pk=request.data.get("assigned_to"), is_active=True).first() \
            or mistake.employee
        if not can_assign_to(request.user, assignee):
            raise PermissionDenied("You can assign only to your level or below.")
        title = str(request.data.get("title", "")).strip() \
            or f"Corrective action for {mistake.code}: {mistake.category}"
        try:
            due_days = max(1, min(int(request.data.get("due_days", 1)), 60))
        except (TypeError, ValueError):
            due_days = 1
        task = Task.objects.create(
            title=title[:200],
            description=f"From mistake {mistake.code}: {mistake.description[:800]}",
            assigned_to=assignee, created_by=request.user,
            category="Review", priority="high",
            due_at=timezone.now() + timedelta(days=due_days),
        )
        mistake.corrective_task = task
        mistake.save(update_fields=["corrective_task"])
        log(mistake, request.user, f"Corrective task created: {task.code} → "
            f"{assignee.get_full_name() or assignee.username}, due in {due_days} day(s)")
        notify(assignee, "task_assigned",
               f"Corrective task {task.code}: {task.title}"[:200],
               "\n".join([
                   f"Task: {task.code} - {task.title}",
                   f"Why: fixing mistake {mistake.code} ({mistake.category})",
                   f"Raised for: {mistake.employee.get_full_name() or mistake.employee.username}",
                   f"Due: {timezone.localtime(task.due_at):%d %b %Y, %I:%M %p}"
                   if task.due_at else "Due: not set",
                   "",
                   mistake.description[:300] if mistake.description else "",
                   "",
                   "Complete this task to close the mistake.",
               ]), link="/tasks")
        return Response(MistakeSerializer(mistake).data, status=http.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        return Response(MistakeEventSerializer(self.get_object().events.all(), many=True).data)

    # ---- M3: AI assistance + patterns + founder view ---------------------
    @action(detail=True, methods=["post"])
    def ai_suggest(self, request, pk=None):
        """Suggests classification + CAPA for the reviewer — a human still
        saves it. Claude behind AI_ENABLED; rule-based otherwise."""
        from .ai import suggest
        mistake = self.get_object()
        if not can_review(request.user, mistake):
            raise PermissionDenied("Only the reviewer can ask for suggestions.")
        return Response(suggest(mistake))

    @action(detail=False, methods=["get"])
    def patterns(self, request):
        """Cross-employee repeat detection over the caller's scope."""
        from .analytics import patterns
        if not (has_capability(request.user, "tasks.view_all")
                or has_capability(request.user, "tasks.view_department")):
            raise PermissionDenied("Managers and admin only.")
        try:
            days = max(7, min(int(request.query_params.get("days", 90)), 365))
        except (TypeError, ValueError):
            days = 90
        return Response(patterns(days, queryset=self.get_queryset()))

    @action(detail=False, methods=["get"])
    def founder_summary(self, request):
        """Action Required only — critical, SLA misses, escalations, level-3,
        this month's loss, process smells, repeat offenders."""
        from .analytics import founder_summary
        if not has_capability(request.user, "tasks.view_all"):
            raise PermissionDenied("Founder/admin view only.")
        return Response(founder_summary())

    @action(detail=False, methods=["get"])
    def department_scores(self, request):
        """M4: accountability score per department, fully explained."""
        from crm.task_views import _range_bounds
        from .analytics import department_scores
        if not (has_capability(request.user, "tasks.view_all")
                or has_capability(request.user, "tasks.view_department")):
            raise PermissionDenied("Managers and admin only.")
        start, end = _range_bounds(request.query_params.get("range", "this_month"), timezone.now())
        return Response(department_scores(start, end))

    @action(detail=False, methods=["post"])
    def send_digests(self, request):
        """Admin: fire the daily/weekly digests now (testing / manual run)."""
        from .digests import send_daily_manager_summaries, send_weekly_founder_digest
        if not has_capability(request.user, "tasks.view_all"):
            raise PermissionDenied("Admin only.")
        return Response({"daily": send_daily_manager_summaries(force=True),
                         "weekly": send_weekly_founder_digest(force=True)})


class SOPViewSet(viewsets.ModelViewSet):
    """The written-process register. Everyone reads it — an employee needs to
    be able to look up how a job is done. Managers/admin write it."""
    serializer_class = SOPSerializer
    pagination_class = None

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [HasCapability.of("tasks.assign")()]

    def get_queryset(self):
        qs = SOP.objects.select_related("owner")
        p = self.request.query_params
        if p.get("all") != "true":
            qs = qs.filter(active=True)
        if p.get("department"):
            qs = qs.filter(department=p["department"])
        if p.get("category"):
            qs = qs.filter(category__iexact=p["category"])
        if p.get("search"):
            from django.db.models import Q
            term = p["search"].strip()
            qs = qs.filter(Q(title__icontains=term) | Q(steps__icontains=term)
                           | Q(common_errors__icontains=term))
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_destroy(self, instance):
        instance.active = False     # keep history: old mistakes still cite it
        instance.save(update_fields=["active"])

    @action(detail=True, methods=["post"])
    def new_version(self, request, pk=None):
        """Supersede a process without losing the old one, so a mistake from
        March is still judged against March's process."""
        old = self.get_object()
        version = str(request.data.get("version", "")).strip()
        if not version:
            raise ValidationError({"version": "Name the new version, e.g. v2."})
        if SOP.objects.filter(title=old.title, version=version).exists():
            raise ValidationError({"version": f"{old.title} {version} already exists."})
        new = SOP.objects.create(
            title=old.title, department=old.department, category=old.category,
            version=version,
            steps=request.data.get("steps", old.steps),
            checks=request.data.get("checks", old.checks),
            common_errors=request.data.get("common_errors", old.common_errors),
            owner=old.owner, created_by=request.user)
        old.active = False
        old.save(update_fields=["active"])
        return Response(SOPSerializer(new).data, status=http.HTTP_201_CREATED)


class MistakeCategoryViewSet(viewsets.ModelViewSet):
    """Configurable categories — everyone reads, admins add/edit."""
    pagination_class = None
    serializer_class = MistakeCategorySerializer

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [HasCapability.of("settings.manage")()]

    def get_queryset(self):
        return MistakeCategory.objects.filter(active=True)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_destroy(self, instance):
        instance.active = False
        instance.save(update_fields=["active"])


class MistakeSettingsView(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        return Response(MistakeSettingsSerializer(MistakeSettings.get()).data)

    def create(self, request):
        if not has_capability(request.user, "settings.manage"):
            raise PermissionDenied("Only an admin can change SLA rules.")
        cfg = MistakeSettings.get()
        ser = MistakeSettingsSerializer(cfg, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save(updated_by=request.user)
        return Response(ser.data)
