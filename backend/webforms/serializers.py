from rest_framework import serializers

from crm.serializers import UserBriefSerializer

from .models import FieldType, Form, FormField, FormSubmission


class FormFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormField
        fields = ["id", "label", "type", "required", "options", "lead_attr", "order"]

    def validate(self, attrs):
        ftype = attrs.get("type", getattr(self.instance, "type", FieldType.SHORT_TEXT))
        options = attrs.get("options", getattr(self.instance, "options", []) or [])
        if ftype in (FieldType.DROPDOWN, FieldType.RADIO, FieldType.CHECKBOX):
            clean = [str(o).strip() for o in options if str(o).strip()]
            if len(clean) < 1:
                raise serializers.ValidationError({"options": "Add at least one option."})
            attrs["options"] = clean
        else:
            attrs["options"] = []
        return attrs


class FormSerializer(serializers.ModelSerializer):
    fields = FormFieldSerializer(many=True, read_only=True)
    created_by_detail = UserBriefSerializer(source="created_by", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    submission_count = serializers.IntegerField(source="submissions.count", read_only=True)

    class Meta:
        model = Form
        fields = ["id", "name", "description", "status", "status_display",
                  "public_token", "created_by_detail", "fields", "submission_count",
                  "create_lead", "lead_department", "create_task", "task_title",
                  "created_at", "updated_at"]
        read_only_fields = ["public_token", "status"]


class PublicFormSerializer(serializers.ModelSerializer):
    """What an anonymous visitor sees -- no tokens, no integration config."""
    fields = FormFieldSerializer(many=True, read_only=True)

    class Meta:
        model = Form
        fields = ["name", "description", "fields"]


class SubmissionSerializer(serializers.ModelSerializer):
    person = serializers.CharField(read_only=True)
    lead_name = serializers.CharField(source="lead.customer_name", read_only=True, default=None)
    task_title = serializers.CharField(source="task.title", read_only=True, default=None)
    files = serializers.SerializerMethodField()

    class Meta:
        model = FormSubmission
        fields = ["id", "person", "answers", "files", "lead", "lead_name",
                  "task", "task_title", "created_at"]

    def get_files(self, obj):
        return [{"field_id": f.field_id, "filename": f.filename, "url": f.file.url}
                for f in obj.files.all()]
