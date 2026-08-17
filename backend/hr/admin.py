from django.contrib import admin

from .models import (
    Attendance, AttendanceCorrection, FaceProfile, LeaveRequest, LeaveType,
    OfficeLocation,
)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "status", "check_in", "check_out", "working_minutes")
    list_filter = ("status", "date")


@admin.register(LeaveRequest)
class LeaveAdmin(admin.ModelAdmin):
    list_display = ("user", "leave_type", "start_date", "end_date", "days", "status")
    list_filter = ("status", "leave_type")


admin.site.register(OfficeLocation)
admin.site.register(LeaveType)
admin.site.register(AttendanceCorrection)
admin.site.register(FaceProfile)
