from django.utils import timezone
from rest_framework import status as http, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import ROLE_CAPABILITIES, HasCapability, has_capability

from . import services
from .models import (
    Attendance, AttendanceCorrection, CorrectionStatus, FaceProfile,
    LeaveRequest, LeaveStatus, LeaveType, OfficeLocation,
)
from .serializers import (
    AttendanceSerializer, CorrectionSerializer, LeaveRequestSerializer,
    LeaveTypeSerializer, MarkSerializer, OfficeLocationSerializer,
)


def can_approve(user) -> bool:
    return has_capability(user, "hr.approve")


def can_manage_hr(user) -> bool:
    return has_capability(user, "hr.manage")


APPROVER_ROLES = [role for role, caps in ROLE_CAPABILITIES.items() if "hr.approve" in caps]


def other_approvers(user):
    """Everyone except `user` who could approve their request."""
    return User.objects.filter(is_active=True, role__in=APPROVER_ROLES).exclude(pk=user.pk)


def _self_review_message(user) -> str:
    """Nobody approves their own request -- not even an admin. If there is
    literally no one else who can, say so plainly instead of allowing it."""
    base = "You cannot approve your own request — it must be reviewed by someone else."
    if not other_approvers(user).exists():
        return (base + " No other approver exists yet: add an HR Manager (or another "
                "admin) in My Team, and ask them to review it.")
    names = ", ".join(u.get_full_name() or u.username for u in other_approvers(user)[:5])
    return f"{base} Ask one of: {names}."


def managed_users(user):
    """Employees whose attendance/leave this user may see."""
    if can_manage_hr(user):
        return User.objects.filter(is_active=True)
    if can_approve(user):
        return User.objects.filter(is_active=True, department=user.department)
    return User.objects.filter(pk=user.pk)


def _target_user(request, param="user"):
    """Resolve ?user=<id>, enforcing scope. Defaults to self."""
    uid = request.query_params.get(param)
    if not uid or str(uid) == str(request.user.id):
        return request.user
    target = managed_users(request.user).filter(pk=uid).first()
    if not target:
        raise PermissionDenied("You cannot view this employee's records.")
    return target


# ------------------------------------------------------------ attendance

class AttendanceViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = AttendanceSerializer

    def get_queryset(self):
        qs = Attendance.objects.select_related("user", "location").filter(
            user__in=managed_users(self.request.user))
        p = self.request.query_params
        if p.get("user"):
            qs = qs.filter(user_id=p["user"])
        elif p.get("scope") != "team":
            qs = qs.filter(user=self.request.user)
        if p.get("from"):
            qs = qs.filter(date__gte=p["from"])
        if p.get("to"):
            qs = qs.filter(date__lte=p["to"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        return qs

    @action(detail=False, methods=["get"])
    def today(self, request):
        rec = Attendance.objects.filter(user=request.user, date=timezone.localdate()).first()
        conf = services.cfg()
        return Response({
            "attendance": AttendanceSerializer(rec).data if rec else None,
            "can_check_in": not (rec and rec.check_in),
            "can_check_out": bool(rec and rec.check_in and not rec.check_out),
            "geofence_enabled": conf["geofence_enabled"],
            "face_enabled": conf["face_enabled"],
            "face_self_enroll": conf["face_self_enroll"],
            "face_enrolled": FaceProfile.objects.filter(user=request.user).exists(),
            "work_start": conf["work_start"], "work_end": conf["work_end"],
        })

    def _mark(self, request, fn):
        ser = MarkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            rec = fn(request.user, d.get("latitude"), d.get("longitude"), d.get("face_descriptor"))
        except services.HRError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(AttendanceSerializer(rec).data, status=http.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def check_in(self, request):
        return self._mark(request, services.check_in)

    @action(detail=False, methods=["post"])
    def check_out(self, request):
        return self._mark(request, services.check_out)

    @action(detail=False, methods=["get"])
    def monthly(self, request):
        today = timezone.localdate()
        try:
            year = int(request.query_params.get("year", today.year))
            month = int(request.query_params.get("month", today.month))
            if not 1 <= month <= 12:
                raise ValueError
        except ValueError:
            raise ValidationError({"month": "Invalid year/month."})
        target = _target_user(request)
        data = services.monthly_report(target, year, month)
        data["user"] = {"id": target.id, "name": target.get_full_name() or target.username}
        return Response(data)

    @action(detail=False, methods=["get"], permission_classes=[HasCapability.of("hr.approve")])
    def team_today(self, request):
        return Response(services.today_summary(list(managed_users(request.user))))

    @action(detail=False, methods=["post"], permission_classes=[HasCapability.of("hr.manage")])
    def manual_mark(self, request):
        """HR override: mark an employee present/half-day/absent by hand —
        for the day the face lock (or their phone) refuses to cooperate.
        Always audited: the record notes who marked it."""
        target = User.objects.filter(pk=request.data.get("user"), is_active=True).first()
        if not target:
            raise ValidationError({"user": "Unknown or inactive employee."})
        status_value = request.data.get("status", "present")
        if status_value not in ("present", "half_day", "absent"):
            raise ValidationError({"status": "Use present, half_day or absent."})
        try:
            day = (timezone.datetime.strptime(request.data["date"], "%Y-%m-%d").date()
                   if request.data.get("date") else timezone.localdate())
        except (ValueError, TypeError):
            raise ValidationError({"date": "Use YYYY-MM-DD."})
        if day > timezone.localdate():
            raise ValidationError({"date": "Cannot mark attendance for a future date."})

        record, _ = Attendance.objects.get_or_create(user=target, date=day)
        record.status = status_value
        reason = str(request.data.get("reason", "")).strip()[:120]
        record.note = (f"Marked {status_value} by {request.user.get_full_name() or request.user.username}"
                       + (f": {reason}" if reason else ""))
        record.save(update_fields=["status", "note"])
        return Response(AttendanceSerializer(record).data)


class CorrectionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = CorrectionSerializer

    def get_queryset(self):
        qs = AttendanceCorrection.objects.select_related("user", "reviewed_by")
        if self.request.query_params.get("scope") == "team" and can_approve(self.request.user):
            return qs.filter(user__in=managed_users(self.request.user))
        return qs.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_destroy(self, instance):
        if instance.user_id != self.request.user.id or instance.status != CorrectionStatus.PENDING:
            raise PermissionDenied("Only your own pending requests can be withdrawn.")
        instance.delete()

    @action(detail=True, methods=["post"], permission_classes=[HasCapability.of("hr.approve")])
    def review(self, request, pk=None):
        correction = AttendanceCorrection.objects.filter(
            pk=pk, user__in=managed_users(request.user)).first()
        if not correction:
            raise PermissionDenied("You cannot review this request.")
        if correction.user_id == request.user.id:
            raise PermissionDenied(_self_review_message(request.user))
        if correction.status != CorrectionStatus.PENDING:
            raise ValidationError({"detail": "This request has already been reviewed."})
        decision = request.data.get("decision")
        if decision not in ("approved", "rejected"):
            raise ValidationError({"decision": "Use 'approved' or 'rejected'."})
        correction.status = decision
        correction.reviewed_by = request.user
        correction.remarks = str(request.data.get("remarks", ""))[:300]
        correction.save()

        if decision == CorrectionStatus.APPROVED:
            rec, _ = Attendance.objects.get_or_create(user=correction.user, date=correction.date)
            if correction.requested_check_in:
                rec.check_in = correction.requested_check_in
            if correction.requested_check_out:
                rec.check_out = correction.requested_check_out
            if rec.check_in and rec.check_out:
                rec.working_minutes = max(0, int((rec.check_out - rec.check_in).total_seconds() // 60))
                hours = rec.working_minutes / 60
                rec.status = ("half_day" if hours < services.cfg()["half_day_hours"]
                              else "late" if rec.is_late else "present")
            rec.note = f"Corrected by {request.user.username}"
            rec.save()
        return Response(CorrectionSerializer(correction).data)


# ----------------------------------------------------------------- leave

class LeaveTypeViewSet(viewsets.ModelViewSet):
    serializer_class = LeaveTypeSerializer
    queryset = LeaveType.objects.all()
    pagination_class = None

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [HasCapability.of("hr.manage")()]


class LeaveRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = LeaveRequestSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = LeaveRequest.objects.select_related("user", "leave_type", "reviewed_by")
        p = self.request.query_params
        if p.get("scope") == "team" and can_approve(self.request.user):
            qs = qs.filter(user__in=managed_users(self.request.user))
        else:
            qs = qs.filter(user=self.request.user)
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        return qs

    def perform_create(self, serializer):
        data = serializer.validated_data
        days = len(services.leave_working_days(data["start_date"], data["end_date"]))
        if days == 0:
            raise ValidationError({"start_date": "That range has no working days (holidays/week-offs only)."})
        overlap = LeaveRequest.objects.filter(
            user=self.request.user,
            status__in=[LeaveStatus.PENDING, LeaveStatus.APPROVED],
            start_date__lte=data["end_date"], end_date__gte=data["start_date"],
        ).exists()
        if overlap:
            raise ValidationError({"detail": "You already have a leave request covering these dates."})
        serializer.save(user=self.request.user, days=days)

    def perform_update(self, serializer):
        if self.get_object().status != LeaveStatus.PENDING:
            raise ValidationError({"detail": "Only pending requests can be edited."})
        serializer.save()

    def perform_destroy(self, instance):
        raise PermissionDenied("Cancel the request instead of deleting it.")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        leave = self.get_object()
        if leave.user_id != request.user.id:
            raise PermissionDenied("You can only cancel your own leave.")
        if leave.status not in (LeaveStatus.PENDING, LeaveStatus.APPROVED):
            raise ValidationError({"detail": "This request cannot be cancelled."})
        if leave.status == LeaveStatus.APPROVED and leave.start_date <= timezone.localdate():
            raise ValidationError({"detail": "Approved leave that has already started cannot be cancelled."})
        was_approved = leave.status == LeaveStatus.APPROVED
        leave.status = LeaveStatus.CANCELLED
        leave.save(update_fields=["status"])
        if was_approved:
            services.revoke_leave_attendance(leave)
        return Response(LeaveRequestSerializer(leave).data)

    @action(detail=True, methods=["post"], permission_classes=[HasCapability.of("hr.approve")])
    def review(self, request, pk=None):
        leave = LeaveRequest.objects.filter(pk=pk, user__in=managed_users(request.user)).first()
        if not leave:
            raise PermissionDenied("You cannot review this request.")
        if leave.user_id == request.user.id:
            raise PermissionDenied(_self_review_message(request.user))
        if leave.status != LeaveStatus.PENDING:
            raise ValidationError({"detail": "This request has already been reviewed."})
        decision = request.data.get("decision")
        if decision not in ("approved", "rejected"):
            raise ValidationError({"decision": "Use 'approved' or 'rejected'."})
        leave.status = decision
        leave.reviewed_by = request.user
        leave.remarks = str(request.data.get("remarks", ""))[:300]
        leave.reviewed_at = timezone.now()
        leave.save()
        if decision == LeaveStatus.APPROVED:
            services.apply_leave_to_attendance(leave)

        from notifications.service import notify
        notify(leave.user, "leave_reviewed",
               f"Leave {leave.get_status_display().lower()}: {leave.leave_type.name}",
               f"{leave.start_date} to {leave.end_date} ({leave.days} day(s))"
               + (f"\nRemarks: {leave.remarks}" if leave.remarks else ""),
               link="/hr")
        return Response(LeaveRequestSerializer(leave).data)

    @action(detail=False, methods=["get"])
    def balances(self, request):
        target = _target_user(request)
        return Response(services.leave_balances(target))


# ------------------------------------------------------- admin/geo/face

class OfficeLocationViewSet(viewsets.ModelViewSet):
    serializer_class = OfficeLocationSerializer
    queryset = OfficeLocation.objects.all()
    pagination_class = None

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [HasCapability.of("hr.manage")()]


@api_view(["POST", "DELETE"])
@permission_classes([HasCapability.of("hr.manage")])
def face_enrolment(request, user_id):
    """Admin-only enrolment/removal. Stores only a numeric descriptor."""
    target = User.objects.filter(pk=user_id).first()
    if not target:
        return Response({"detail": "Unknown user."}, status=404)
    if request.method == "DELETE":
        FaceProfile.objects.filter(user=target).delete()
        return Response({"enrolled": False})
    descriptor = request.data.get("descriptor")
    if not isinstance(descriptor, list) or not 32 <= len(descriptor) <= 512:
        return Response({"descriptor": "Send the face descriptor vector (32-512 floats)."}, status=400)
    try:
        descriptor = [float(x) for x in descriptor]
    except (TypeError, ValueError):
        return Response({"descriptor": "Descriptor must be numeric."}, status=400)
    FaceProfile.objects.update_or_create(
        user=target, defaults={"descriptor": descriptor, "enrolled_by": request.user})
    return Response({"enrolled": True, "user": target.id})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def hr_config(request):
    conf = services.cfg()
    return Response({
        "geofence_enabled": conf["geofence_enabled"],
        "face_enabled": conf["face_enabled"],
        "work_start": conf["work_start"], "work_end": conf["work_end"],
        "week_offs": conf["week_offs"],
        "can_approve": can_approve(request.user),
        "can_manage": can_manage_hr(request.user),
    })
