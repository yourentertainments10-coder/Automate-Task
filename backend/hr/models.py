"""Leave & Attendance.

Attendance is one row per employee per day. Check-in/out capture GPS (and
optionally a face descriptor); the server decides status, lateness and
working hours -- never the client. Approved leave writes LEAVE days into
attendance so both modules agree on where someone was.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class OfficeLocation(models.Model):
    """A geo-fence: employees may only mark attendance inside `radius_m`."""
    name = models.CharField(max_length=120, unique=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius_m = models.PositiveIntegerField(default=200)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.radius_m} m)"


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    HALF_DAY = "half_day", "Half Day"
    LATE = "late", "Late"
    LEAVE = "leave", "Leave"
    HOLIDAY = "holiday", "Holiday"
    WEEK_OFF = "week_off", "Week Off"


class Attendance(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="attendance")
    date = models.DateField()
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    check_in_lat = models.FloatField(null=True, blank=True)
    check_in_lng = models.FloatField(null=True, blank=True)
    check_out_lat = models.FloatField(null=True, blank=True)
    check_out_lng = models.FloatField(null=True, blank=True)
    location = models.ForeignKey(OfficeLocation, null=True, blank=True,
                                 on_delete=models.SET_NULL)
    status = models.CharField(max_length=10, choices=AttendanceStatus.choices,
                              default=AttendanceStatus.PRESENT)
    working_minutes = models.PositiveIntegerField(default=0)
    is_late = models.BooleanField(default=False)
    is_early_checkout = models.BooleanField(default=False)
    face_verified = models.BooleanField(default=False)
    face_confidence = models.FloatField(null=True, blank=True)
    leave_request = models.ForeignKey("hr.LeaveRequest", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="attendance_days")
    note = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]
        constraints = [models.UniqueConstraint(fields=["user", "date"], name="uniq_attendance_day")]
        indexes = [models.Index(fields=["user", "date"]), models.Index(fields=["date"])]

    @property
    def missing_checkout(self) -> bool:
        return bool(self.check_in and not self.check_out and self.date < timezone.localdate())

    def __str__(self):
        return f"{self.user} {self.date} {self.status}"


class CorrectionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class AttendanceCorrection(models.Model):
    """"I forgot to check out" -- reviewed by a manager/admin."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="attendance_corrections")
    date = models.DateField()
    requested_check_in = models.DateTimeField(null=True, blank=True)
    requested_check_out = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(max_length=1000)
    status = models.CharField(max_length=10, choices=CorrectionStatus.choices,
                              default=CorrectionStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="reviewed_corrections")
    remarks = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class LeaveType(models.Model):
    name = models.CharField(max_length=60, unique=True)
    annual_quota = models.PositiveIntegerField(default=12)
    paid = models.BooleanField(default=True)
    requires_document = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LeaveStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class LeaveRequest(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    start_date = models.DateField()
    end_date = models.DateField()
    days = models.PositiveIntegerField(default=1)
    reason = models.TextField(max_length=1000)
    document = models.FileField(upload_to="leave_docs/", null=True, blank=True)
    status = models.CharField(max_length=10, choices=LeaveStatus.choices,
                              default=LeaveStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="reviewed_leaves")
    remarks = models.CharField(max_length=300, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "status"])]

    def __str__(self):
        return f"{self.user} {self.leave_type} {self.start_date}..{self.end_date} [{self.status}]"


class FaceProfile(models.Model):
    """Optional biometric enrolment. We store ONLY a numeric descriptor
    (never an image), and only when an admin enrols the employee. Matching
    is euclidean distance against this descriptor, gated by
    FACE_MATCH_THRESHOLD; the whole feature is off unless
    FACE_RECOGNITION_ENABLED=true."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="face_profile")
    descriptor = models.JSONField(default=list)
    enrolled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="enrolled_faces")
    enrolled_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Face profile: {self.user}"
