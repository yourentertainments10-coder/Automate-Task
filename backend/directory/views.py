from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import HasCapability, has_capability
from crm.models import Task, TaskActivity, TaskTemplate
from crm.scoping import can_assign_to
from crm.serializers import TaskSerializer, TaskTemplateSerializer

from .models import DirectoryTemplate, Industry


class IndustrySerializer(serializers.ModelSerializer):
    template_count = serializers.IntegerField(read_only=True)
    categories = serializers.SerializerMethodField()

    class Meta:
        model = Industry
        fields = ["id", "name", "slug", "icon", "description", "template_count", "categories"]

    def get_categories(self, obj):
        return sorted({t.category for t in obj.templates.all() if t.active})


class DirectoryTemplateSerializer(serializers.ModelSerializer):
    industry_name = serializers.CharField(source="industry.name", read_only=True)
    industry_icon = serializers.CharField(source="industry.icon", read_only=True)
    step_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DirectoryTemplate
        fields = ["id", "industry", "industry_name", "industry_icon", "category",
                  "name", "description", "priority", "frequency", "tags",
                  "steps", "step_count", "active"]


class IndustryViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse industries (read-only for everyone; content is seeded)."""
    permission_classes = [IsAuthenticated]
    serializer_class = IndustrySerializer
    pagination_class = None

    def get_queryset(self):
        return (Industry.objects.filter(active=True)
                .prefetch_related("templates")
                .annotate(template_count=Count("templates", filter=Q(templates__active=True))))


class DirectoryTemplateViewSet(viewsets.ModelViewSet):
    """Browse/search the library. Writes are admin-only — the normal way to
    add content is `manage.py load_directory <file.json|csv>`."""
    serializer_class = DirectoryTemplateSerializer
    pagination_class = None

    # "Using" a template is a normal member action; only editing the library
    # content itself (create/update/delete) is admin-only.
    USE_ACTIONS = ("add_to_my_templates", "create_tasks")

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS") or self.action in self.USE_ACTIONS:
            return [IsAuthenticated()]
        return [HasCapability.of("settings.manage")()]

    def get_queryset(self):
        qs = DirectoryTemplate.objects.select_related("industry").filter(active=True)
        p = self.request.query_params
        if p.get("industry"):
            qs = qs.filter(industry_id=p["industry"])
        if p.get("slug"):
            qs = qs.filter(industry__slug=p["slug"])
        if p.get("category"):
            qs = qs.filter(category__iexact=p["category"])
        if p.get("tag"):
            qs = [t for t in qs if p["tag"].lower() in [str(x).lower() for x in (t.tags or [])]]
            return qs
        if p.get("search"):
            s = p["search"]
            qs = qs.filter(Q(name__icontains=s) | Q(description__icontains=s)
                           | Q(category__icontains=s))
        return qs

    # ---- using a template ------------------------------------------------
    @action(detail=True, methods=["post"])
    def add_to_my_templates(self, request, pk=None):
        """Copy every step into the company's own Task Templates."""
        if not has_capability(request.user, "tasks.assign"):
            raise PermissionDenied("Your role cannot manage task templates.")
        tpl = self.get_object()
        created = []
        for step in (tpl.steps or []):
            title = str(step.get("title", "")).strip()
            if not title:
                continue
            base = f"{tpl.name} — {title}"[:120]
            name, n = base, 2
            while TaskTemplate.objects.filter(name=name).exists():
                suffix = f" ({n})"
                name = base[:120 - len(suffix)] + suffix
                n += 1
            created.append(TaskTemplate.objects.create(
                name=name, category=tpl.category, title=title[:200],
                description=str(step.get("description", ""))[:2000],
                priority=tpl.priority, frequency=tpl.frequency,
                created_by=request.user,
            ))
        if not created:
            raise ValidationError({"detail": "This template has no steps to copy."})
        return Response(TaskTemplateSerializer(created, many=True).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def create_tasks(self, request, pk=None):
        """Turn the template's steps into real tasks, spaced by offset_days."""
        tpl = self.get_object()
        assignee_id = request.data.get("assigned_to")
        assignee = request.user
        if assignee_id and str(assignee_id) != str(request.user.id):
            assignee = User.objects.filter(pk=assignee_id, is_active=True).first()
            if not assignee:
                raise ValidationError({"assigned_to": "Unknown or inactive user."})
            if not can_assign_to(request.user, assignee):
                raise PermissionDenied("You can assign tasks to people at your level or below.")

        group = None
        if request.data.get("group"):
            from workspace.access import is_workspace_admin, user_group_ids
            gid = int(request.data["group"])
            if gid not in user_group_ids(request.user) and not is_workspace_admin(request.user):
                raise PermissionDenied("You can only create tasks in groups you belong to.")
            from workspace.models import Group
            group = Group.objects.filter(pk=gid).first()

        start = timezone.now()
        created = []
        for step in (tpl.steps or []):
            title = str(step.get("title", "")).strip()
            if not title:
                continue
            offset = int(step.get("offset_days") or 0)
            task = Task.objects.create(
                title=title[:200],
                description=str(step.get("description", ""))[:2000],
                category=tpl.category[:60], frequency=tpl.frequency,
                priority=tpl.priority, assigned_to=assignee, created_by=request.user,
                group=group, due_at=start + timedelta(days=offset) if offset else None,
            )
            task.subscribers.add(request.user)
            TaskActivity.objects.create(
                task=task, actor=request.user,
                text=f"Created from directory template '{tpl.name}'")
            created.append(task)
        if not created:
            raise ValidationError({"detail": "This template has no steps."})

        if assignee != request.user:
            from notifications.service import notify
            notify(assignee, "task_assigned",
                   f"{len(created)} new tasks assigned to you: {tpl.name}"[:200],
                   "\n".join([
                       f"{len(created)} tasks were created for you from the",
                       f"'{tpl.name}' template ({tpl.industry.name} library).",
                       "",
                   ] + [f"  - {t.code} {t.title}" for t in created[:10]]
                     + ([f"  ...and {len(created) - 10} more"] if len(created) > 10 else [])
                     + ["", "Open Tasks > My Tasks to see due dates and start."]),
                   link="/tasks")
        return Response(TaskSerializer(created, many=True, context={"request": request}).data,
                        status=status.HTTP_201_CREATED)
