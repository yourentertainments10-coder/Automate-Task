from rest_framework import serializers

from accounts.models import User

from .models import (
    AssignmentRule, Holiday, Lead, LeadDocument, LeadEvent, Quotation,
    Task, TaskActivity, TaskAttachment, TaskCategory, TaskChangeRequest,
    TaskChecklistItem, TaskSettings, TaskTemplate,
)


class TaskCategorySerializer(serializers.ModelSerializer):
    department_display = serializers.CharField(source="get_department_display", read_only=True)

    class Meta:
        model = TaskCategory
        fields = ["id", "name", "department", "department_display", "active"]
        # active is toggled via DELETE (deactivate), never set on create --
        # a form POST without the field must not save active=False
        read_only_fields = ["active"]

    def validate(self, attrs):
        name = attrs.get("name", "").strip()
        department = attrs.get("department", "")
        if name and TaskCategory.objects.filter(
                name__iexact=name, department=department, active=True).exists():
            raise serializers.ValidationError({"name": "This category already exists."})
        attrs["name"] = name
        return attrs


class UserBriefSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "name", "role"]

    def get_name(self, obj):
        return obj.get_full_name() or obj.username


class LeadEventSerializer(serializers.ModelSerializer):
    actor = UserBriefSerializer(read_only=True)
    type_display = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = LeadEvent
        fields = ["id", "type", "type_display", "body", "actor", "payload", "created_at"]


class LeadDocumentSerializer(serializers.ModelSerializer):
    uploaded_by = UserBriefSerializer(read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = LeadDocument
        fields = ["id", "filename", "url", "uploaded_by", "created_at"]

    def get_url(self, obj):
        return obj.file.url if obj.file else None


class QuotationSerializer(serializers.ModelSerializer):
    created_by = UserBriefSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Quotation
        fields = ["id", "number", "amount", "status", "status_display", "notes", "created_by", "created_at"]
        read_only_fields = ["number"]


class LeadSerializer(serializers.ModelSerializer):
    assigned_to_detail = UserBriefSerializer(source="assigned_to", read_only=True)
    created_by_detail = UserBriefSerializer(source="created_by", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    department_display = serializers.CharField(source="get_department_display", read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            "id", "customer_name", "phone", "email", "company", "requirement",
            "source", "source_display", "department", "department_display",
            "status", "status_display", "priority", "priority_display",
            "assigned_to", "assigned_to_detail", "created_by_detail",
            "follow_up_at", "estimated_value", "is_overdue", "ai_meta", "can_edit",
            "created_at", "updated_at",
        ]
        read_only_fields = ["ai_meta", "created_at", "updated_at"]

    def get_can_edit(self, obj):
        from .scoping import can_edit_lead
        request = self.context.get("request")
        return bool(request and can_edit_lead(request.user, obj))


class NoteSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4000)


class TaskSerializer(serializers.ModelSerializer):
    assigned_to_detail = UserBriefSerializer(source="assigned_to", read_only=True)
    created_by_detail = UserBriefSerializer(source="created_by", read_only=True)
    lead_name = serializers.CharField(source="lead.customer_name", read_only=True, default=None)
    group_name = serializers.CharField(source="group.name", read_only=True, default=None)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    frequency_display = serializers.CharField(source="get_frequency_display", read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    subscribed = serializers.SerializerMethodField()

    code = serializers.CharField(read_only=True)
    parent_code = serializers.CharField(source="parent.code", read_only=True, default=None)
    pending_change_requests = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id", "code", "title", "description", "category", "department",
            "frequency", "frequency_display", "parent", "parent_code",
            "repeat_until", "lead", "lead_name", "group", "group_name",
            "assigned_to", "assigned_to_detail", "created_by_detail",
            "status", "status_display", "priority", "priority_display",
            "due_at", "is_overdue", "effort_minutes", "assignee_estimate_minutes",
            "progress_percent", "actual_minutes",
            "completion_note", "completed_at", "deleted_at", "subscribed",
            "pending_change_requests", "created_at", "updated_at",
        ]
        read_only_fields = ["assignee_estimate_minutes", "progress_percent",
                            "actual_minutes", "completion_note",
                            "completed_at", "deleted_at", "created_at", "updated_at"]

    def get_pending_change_requests(self, obj):
        return sum(1 for r in obj.change_requests.all() if r.status == "pending") \
            if hasattr(obj, "_prefetched_objects_cache") and "change_requests" in obj._prefetched_objects_cache \
            else obj.change_requests.filter(status="pending").count()

    def get_subscribed(self, obj):
        request = self.context.get("request")
        if not request:
            return False
        return obj.subscribers.filter(pk=request.user.pk).exists()


class TaskActivitySerializer(serializers.ModelSerializer):
    actor = UserBriefSerializer(read_only=True)
    task_title = serializers.CharField(source="task.title", read_only=True)
    task_code = serializers.CharField(source="task.code", read_only=True)
    task_assignee = serializers.SerializerMethodField()

    class Meta:
        model = TaskActivity
        fields = ["id", "task", "task_title", "task_code", "task_assignee",
                  "actor", "text", "kind", "created_at"]

    def get_task_assignee(self, obj):
        who = obj.task.assigned_to if obj.task_id else None
        return (who.get_full_name() or who.username) if who else None


class TaskChecklistItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskChecklistItem
        fields = ["id", "text", "done", "order"]


class TaskTemplateSerializer(serializers.ModelSerializer):
    created_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = TaskTemplate
        fields = ["id", "name", "category", "title", "description",
                  "priority", "frequency", "created_by", "created_at"]


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ["id", "name", "date"]


class TaskAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = UserBriefSerializer(read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = TaskAttachment
        fields = ["id", "filename", "url", "uploaded_by", "created_at"]

    def get_url(self, obj):
        return obj.file.url if obj.file else None


# Which task fields a Modification Request may propose to change
CHANGEABLE_TASK_FIELDS = {
    "title", "description", "due_at", "effort_minutes", "priority",
    "frequency", "repeat_until", "category", "assigned_to", "cancel",
}


class TaskChangeRequestSerializer(serializers.ModelSerializer):
    requested_by = UserBriefSerializer(read_only=True)
    reviewed_by = UserBriefSerializer(read_only=True)
    task_code = serializers.CharField(source="task.code", read_only=True)
    task_title = serializers.CharField(source="task.title", read_only=True)
    task_assignee = serializers.CharField(source="task.assigned_to.username", read_only=True)
    # who the task actually belongs to, so an approver never has to guess
    task_assignee_name = serializers.SerializerMethodField()
    task_created_by_name = serializers.SerializerMethodField()
    changes_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = TaskChangeRequest
        fields = ["id", "task", "task_code", "task_title", "task_assignee",
                  "task_assignee_name", "task_created_by_name", "changes_display",
                  "requested_by", "changes", "reason", "status", "status_display",
                  "escalated", "reviewed_by", "remarks", "reviewed_at", "created_at"]
        read_only_fields = ["task", "status", "escalated", "remarks", "reviewed_at"]

    def _name(self, who):
        return (who.get_full_name() or who.username) if who else None

    def get_task_assignee_name(self, obj):
        return self._name(obj.task.assigned_to if obj.task_id else None)

    def get_task_created_by_name(self, obj):
        return self._name(obj.task.created_by if obj.task_id else None)

    def get_changes_display(self, obj):
        return obj.describe()

    def validate_changes(self, value):
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError("Propose at least one change.")
        unknown = set(value) - CHANGEABLE_TASK_FIELDS
        if unknown:
            raise serializers.ValidationError(
                f"These fields cannot be changed via a request: {sorted(unknown)}")
        if "effort_minutes" in value and value["effort_minutes"] is not None:
            try:
                if int(value["effort_minutes"]) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                raise serializers.ValidationError("effort_minutes must be a positive number.")
        return value


class TaskSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskSettings
        fields = ["require_completion_remarks", "require_completion_attachment", "updated_at"]


class AssignmentRuleSerializer(serializers.ModelSerializer):
    department_display = serializers.CharField(source="get_department_display", read_only=True)
    members_detail = serializers.SerializerMethodField()

    class Meta:
        model = AssignmentRule
        fields = ["id", "department", "department_display", "strategy",
                  "member_ids", "members_detail", "rr_index", "active", "updated_at"]
        read_only_fields = ["rr_index", "updated_at"]

    def get_members_detail(self, obj):
        users = {u.pk: u for u in User.objects.filter(pk__in=obj.member_ids)}
        return [UserBriefSerializer(users[pk]).data for pk in obj.member_ids if pk in users]

    def validate_member_ids(self, value):
        if not isinstance(value, list) or not all(isinstance(v, int) for v in value):
            raise serializers.ValidationError("member_ids must be a list of user ids.")
        missing = set(value) - set(User.objects.filter(pk__in=value).values_list("pk", flat=True))
        if missing:
            raise serializers.ValidationError(f"Unknown user ids: {sorted(missing)}")
        return value
