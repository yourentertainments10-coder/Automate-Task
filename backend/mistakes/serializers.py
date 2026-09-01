from rest_framework import serializers

from crm.serializers import UserBriefSerializer

from .models import (
    SOP, Mistake, MistakeCategory, MistakeEvent, MistakeSettings,
)


class SOPSerializer(serializers.ModelSerializer):
    department_display = serializers.CharField(source="get_department_display", read_only=True)
    owner_name = serializers.SerializerMethodField()
    step_count = serializers.SerializerMethodField()
    mistake_count = serializers.SerializerMethodField()

    class Meta:
        model = SOP
        fields = ["id", "title", "department", "department_display", "category",
                  "version", "steps", "checks", "common_errors", "active",
                  "owner", "owner_name", "step_count", "mistake_count",
                  "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def get_owner_name(self, obj):
        return (obj.owner.get_full_name() or obj.owner.username) if obj.owner else None

    def get_step_count(self, obj):
        return len(obj.step_list)

    def get_mistake_count(self, obj):
        return obj.mistakes.count()

    def validate_steps(self, value):
        """A process with one vague line cannot settle 'human error or
        process failure?' — which is the whole point of writing it down."""
        steps = [s for s in (value or "").splitlines() if s.strip()]
        if len(steps) < 2:
            raise serializers.ValidationError(
                "Write at least two steps, one per line — a single sentence is "
                "not a process anyone can be measured against.")
        return value


class MistakeCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MistakeCategory
        fields = ["id", "name", "active"]
        read_only_fields = ["active"]

    def validate_name(self, value):
        value = value.strip()
        if MistakeCategory.objects.filter(name__iexact=value, active=True).exists():
            raise serializers.ValidationError("This category already exists.")
        return value


class MistakeSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = MistakeSettings
        fields = ["sla_low_hours", "sla_medium_hours", "sla_high_hours",
                  "sla_critical_hours", "updated_at"]


class MistakeEventSerializer(serializers.ModelSerializer):
    actor = UserBriefSerializer(read_only=True)

    class Meta:
        model = MistakeEvent
        fields = ["id", "actor", "text", "created_at"]


class MistakeSerializer(serializers.ModelSerializer):
    employee_detail = UserBriefSerializer(source="employee", read_only=True)
    manager_detail = UserBriefSerializer(source="manager", read_only=True)
    reported_by_detail = UserBriefSerializer(source="reported_by", read_only=True)
    code = serializers.CharField(read_only=True)
    sla_overdue = serializers.BooleanField(read_only=True)
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    classification_display = serializers.CharField(source="get_classification_display", read_only=True)
    root_cause_display = serializers.CharField(source="get_root_cause_display", read_only=True)
    level3_action_display = serializers.CharField(source="get_level3_action_display", read_only=True)
    repeat_of_code = serializers.CharField(source="repeat_of.code", read_only=True, default=None)
    task_code = serializers.CharField(source="task.code", read_only=True, default=None)
    corrective_task_code = serializers.CharField(source="corrective_task.code", read_only=True, default=None)
    corrective_task_status = serializers.CharField(source="corrective_task.status", read_only=True, default=None)

    class Meta:
        model = Mistake
        fields = [
            "id", "code", "employee", "employee_detail", "department", "manager",
            "manager_detail", "reported_by_detail",
            "category", "severity", "severity_display", "classification",
            "classification_display", "description", "impact", "financial_loss",
            "task", "task_code", "lead",
            "occurrence_level", "repeat_of", "repeat_of_code",
            "explanation", "root_cause", "root_cause_display", "root_cause_note",
            "corrective_action", "preventive_action",
            "sop_name", "sop_version", "sop_step", "sop_followed", "sop_adequate",
            "status", "status_display", "manager_remarks",
            "level3_action", "level3_action_display", "level3_action_note",
            "sla_due_at", "sla_overdue", "escalation_level",
            "corrective_task", "corrective_task_code", "corrective_task_status",
            "resolved_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "department", "manager", "occurrence_level", "repeat_of",
            "explanation", "root_cause", "root_cause_note",
            "corrective_action", "preventive_action", "status",
            "manager_remarks", "level3_action", "level3_action_note",
            "sla_due_at", "escalation_level", "corrective_task",
            "resolved_at", "created_at", "updated_at", "classification",
            "sop_name", "sop_version", "sop_step", "sop_followed", "sop_adequate",
        ]
