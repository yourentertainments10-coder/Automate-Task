from datetime import timedelta

from rest_framework import serializers

from crm.serializers import UserBriefSerializer

from .models import (
    Attendance, AttendanceCorrection, LeaveRequest, LeaveType, OfficeLocation,
)


class OfficeLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = OfficeLocation
        fields = ["id", "name", "latitude", "longitude", "radius_m", "active"]

    def validate(self, attrs):
        lat = attrs.get("latitude", getattr(self.instance, "latitude", 0))
        lng = attrs.get("longitude", getattr(self.instance, "longitude", 0))
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            raise serializers.ValidationError({"latitude": "Invalid coordinates."})
        return attrs


class AttendanceSerializer(serializers.ModelSerializer):
    user_detail = UserBriefSerializer(source="user", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True, default=None)
    missing_checkout = serializers.BooleanField(read_only=True)

    class Meta:
        model = Attendance
        fields = ["id", "user", "user_detail", "date", "check_in", "check_out",
                  "status", "status_display", "working_minutes", "is_late",
                  "is_early_checkout", "missing_checkout", "face_verified",
                  "face_confidence", "location_name", "note"]


class MarkSerializer(serializers.Serializer):
    """Payload for check-in/out. The client sends raw GPS + optional face
    descriptor; every decision is made server-side."""
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    face_descriptor = serializers.ListField(
        child=serializers.FloatField(), required=False, allow_null=True, max_length=512)


class CorrectionSerializer(serializers.ModelSerializer):
    user_detail = UserBriefSerializer(source="user", read_only=True)
    reviewed_by_detail = UserBriefSerializer(source="reviewed_by", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = AttendanceCorrection
        fields = ["id", "user", "user_detail", "date", "requested_check_in",
                  "requested_check_out", "reason", "status", "status_display",
                  "reviewed_by_detail", "remarks", "created_at"]
        read_only_fields = ["user", "status", "reviewed_by_detail", "remarks"]

    def validate(self, attrs):
        if not attrs.get("requested_check_in") and not attrs.get("requested_check_out"):
            raise serializers.ValidationError("Provide a corrected check-in or check-out time.")
        return attrs


class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = ["id", "name", "annual_quota", "paid", "requires_document", "active"]


class LeaveRequestSerializer(serializers.ModelSerializer):
    user_detail = UserBriefSerializer(source="user", read_only=True)
    reviewed_by_detail = UserBriefSerializer(source="reviewed_by", read_only=True)
    leave_type_name = serializers.CharField(source="leave_type.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    document_url = serializers.SerializerMethodField()

    class Meta:
        model = LeaveRequest
        fields = ["id", "user", "user_detail", "leave_type", "leave_type_name",
                  "start_date", "end_date", "days", "reason", "document", "document_url",
                  "status", "status_display", "reviewed_by_detail", "remarks",
                  "reviewed_at", "created_at"]
        read_only_fields = ["user", "days", "status", "reviewed_by_detail",
                            "remarks", "reviewed_at"]
        extra_kwargs = {"document": {"write_only": True, "required": False}}

    def get_document_url(self, obj):
        return obj.document.url if obj.document else None

    def validate(self, attrs):
        start = attrs.get("start_date")
        end = attrs.get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "End date cannot be before the start date."})
        if start and end and (end - start) > timedelta(days=90):
            raise serializers.ValidationError({"end_date": "Leave range cannot exceed 90 days."})
        leave_type = attrs.get("leave_type")
        if leave_type and leave_type.requires_document and not attrs.get("document"):
            raise serializers.ValidationError({"document": f"{leave_type.name} requires a supporting document."})
        return attrs
