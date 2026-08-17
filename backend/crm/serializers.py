from rest_framework import serializers

from accounts.models import User

from .models import (
    AssignmentRule, Holiday, Lead, LeadDocument, LeadEvent, Quotation,
    Task, TaskActivity, TaskTemplate,
)


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

    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "category", "frequency", "frequency_display",
            "lead", "lead_name", "group", "group_name",
            "assigned_to", "assigned_to_detail", "created_by_detail",
            "status", "status_display", "priority", "priority_display",
            "due_at", "is_overdue", "completed_at", "subscribed",
            "created_at", "updated_at",
        ]
        read_only_fields = ["completed_at", "created_at", "updated_at"]

    def get_subscribed(self, obj):
        request = self.context.get("request")
        if not request:
            return False
        return obj.subscribers.filter(pk=request.user.pk).exists()


class TaskActivitySerializer(serializers.ModelSerializer):
    actor = UserBriefSerializer(read_only=True)
    task_title = serializers.CharField(source="task.title", read_only=True)

    class Meta:
        model = TaskActivity
        fields = ["id", "task", "task_title", "actor", "text", "created_at"]


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
