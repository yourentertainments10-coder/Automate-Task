"""HR rules: geo-fence validation, face matching, attendance computation,
leave-day expansion and the monthly report.

Everything that decides a status runs SERVER-SIDE. The client sends raw
GPS coordinates (and optionally a face descriptor); it never sends a
distance, a status or a "verified" flag.
"""
import math
import os
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from crm.models import Holiday

from .models import (
    Attendance, AttendanceStatus, FaceProfile, LeaveRequest, LeaveStatus, OfficeLocation,
)


# ---------------------------------------------------------------- config

def _env(name, default):
    return os.environ.get(name, default)


def cfg():
    return {
        "work_start": _env("HR_WORK_START", "09:30"),
        "work_end": _env("HR_WORK_END", "18:30"),
        "grace_minutes": int(_env("HR_LATE_GRACE_MINUTES", "15")),
        "half_day_hours": float(_env("HR_HALF_DAY_HOURS", "4")),
        "full_day_hours": float(_env("HR_FULL_DAY_HOURS", "8")),
        "week_offs": [int(d) for d in _env("HR_WEEK_OFF_DAYS", "6").split(",") if d.strip().isdigit()],
        "geofence_enabled": _env("GEOFENCE_ENABLED", "false").lower() == "true",
        "face_enabled": _env("FACE_RECOGNITION_ENABLED", "false").lower() == "true",
        "face_threshold": float(_env("FACE_MATCH_THRESHOLD", "0.6")),
    }


def _parse_hhmm(value: str, fallback: time) -> time:
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return fallback


class HRError(Exception):
    """Rejected check-in/out -- message is safe to show the employee."""


# ------------------------------------------------------------- geofence

def haversine_m(lat1, lng1, lat2, lng2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def validate_location(lat, lng):
    """Returns (office, distance_m). Raises HRError when outside every fence.
    With geofencing disabled the coordinates are stored but never enforced."""
    conf = cfg()
    if not conf["geofence_enabled"]:
        return None, None
    offices = list(OfficeLocation.objects.filter(active=True))
    if not offices:
        raise HRError("No office location is configured yet — ask an admin to add one.")
    if lat is None or lng is None:
        raise HRError("Location is required for attendance. Please enable GPS and try again.")
    best, best_d = None, None
    for office in offices:
        d = haversine_m(float(lat), float(lng), office.latitude, office.longitude)
        if best_d is None or d < best_d:
            best, best_d = office, d
    if best_d > best.radius_m:
        raise HRError(
            f"You are {int(best_d)} m from {best.name} (allowed {best.radius_m} m). "
            "Move closer to the office to mark attendance."
        )
    return best, best_d


# ----------------------------------------------------------------- face

def face_distance(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 1.0
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def verify_face(user, descriptor):
    """Returns (verified, confidence). Raises HRError when face attendance
    is required but cannot be established -- we NEVER mark attendance on a
    below-threshold match."""
    conf = cfg()
    if not conf["face_enabled"]:
        return False, None
    profile = FaceProfile.objects.filter(user=user).first()
    if not profile or not profile.descriptor:
        raise HRError("Face attendance is on but your face is not enrolled yet. Ask an admin to enrol you.")
    if not descriptor:
        raise HRError("Face scan required. Allow camera access and try again.")
    if len(descriptor) != len(profile.descriptor):
        raise HRError("Face scan could not be read. Please try again.")
    dist = face_distance(descriptor, profile.descriptor)
    confidence = max(0.0, 1.0 - dist)
    if dist > conf["face_threshold"]:
        raise HRError("Face did not match your enrolled profile. Attendance not marked.")
    return True, round(confidence, 3)


# ----------------------------------------------------- attendance rules

def is_week_off(day: date) -> bool:
    return day.weekday() in cfg()["week_offs"]


def is_holiday(day: date) -> bool:
    return Holiday.objects.filter(date=day).exists()


def check_in(user, lat=None, lng=None, descriptor=None) -> Attendance:
    conf = cfg()
    today = timezone.localdate()
    existing = Attendance.objects.filter(user=user, date=today).first()
    if existing and existing.check_in:
        raise HRError("You have already checked in today.")
    if existing and existing.status == AttendanceStatus.LEAVE:
        raise HRError("You are on approved leave today.")

    office, _ = validate_location(lat, lng)
    verified, confidence = verify_face(user, descriptor)

    now = timezone.localtime()
    start = _parse_hhmm(conf["work_start"], time(9, 30))
    late_cutoff = (datetime.combine(today, start) + timedelta(minutes=conf["grace_minutes"])).time()
    late = now.time() > late_cutoff

    record = existing or Attendance(user=user, date=today)
    record.check_in = timezone.now()
    record.check_in_lat, record.check_in_lng = lat, lng
    record.location = office
    record.is_late = late
    record.status = AttendanceStatus.LATE if late else AttendanceStatus.PRESENT
    record.face_verified = verified
    record.face_confidence = confidence
    record.save()
    return record


def check_out(user, lat=None, lng=None, descriptor=None) -> Attendance:
    conf = cfg()
    today = timezone.localdate()
    record = Attendance.objects.filter(user=user, date=today).first()
    if not record or not record.check_in:
        raise HRError("You have not checked in today.")
    if record.check_out:
        raise HRError("You have already checked out today.")

    validate_location(lat, lng)
    verify_face(user, descriptor)

    record.check_out = timezone.now()
    record.check_out_lat, record.check_out_lng = lat, lng
    record.working_minutes = max(0, int((record.check_out - record.check_in).total_seconds() // 60))

    end = _parse_hhmm(conf["work_end"], time(18, 30))
    record.is_early_checkout = timezone.localtime(record.check_out).time() < end
    hours = record.working_minutes / 60
    if hours < conf["half_day_hours"]:
        record.status = AttendanceStatus.HALF_DAY
    elif record.is_late:
        record.status = AttendanceStatus.LATE
    else:
        record.status = AttendanceStatus.PRESENT
    record.save()
    return record


# ---------------------------------------------------------------- leave

def leave_working_days(start: date, end: date):
    """Dates in the range that are actual working days (no week-offs/holidays)."""
    days, cur = [], start
    while cur <= end:
        if not is_week_off(cur) and not is_holiday(cur):
            days.append(cur)
        cur += timedelta(days=1)
    return days


def apply_leave_to_attendance(leave: LeaveRequest):
    """Approved leave -> LEAVE attendance rows, so reports and check-in agree."""
    for day in leave_working_days(leave.start_date, leave.end_date):
        record, _ = Attendance.objects.get_or_create(
            user=leave.user, date=day,
            defaults={"status": AttendanceStatus.LEAVE, "leave_request": leave},
        )
        if not record.check_in:
            record.status = AttendanceStatus.LEAVE
            record.leave_request = leave
            record.save(update_fields=["status", "leave_request"])


def revoke_leave_attendance(leave: LeaveRequest):
    Attendance.objects.filter(leave_request=leave, check_in__isnull=True).delete()


def leave_balances(user, year=None):
    from .models import LeaveType
    year = year or timezone.localdate().year
    out = []
    for lt in LeaveType.objects.filter(active=True):
        used = sum(
            l.days for l in LeaveRequest.objects.filter(
                user=user, leave_type=lt, status=LeaveStatus.APPROVED,
                start_date__year=year)
        )
        pending = sum(
            l.days for l in LeaveRequest.objects.filter(
                user=user, leave_type=lt, status=LeaveStatus.PENDING,
                start_date__year=year)
        )
        out.append({
            "leave_type": lt.id, "name": lt.name, "paid": lt.paid,
            "quota": lt.annual_quota, "used": used, "pending": pending,
            "balance": max(0, lt.annual_quota - used),
        })
    return out


# --------------------------------------------------------------- report

def monthly_report(user, year: int, month: int) -> dict:
    """Day-by-day + totals for one employee/month. Days with no record are
    classified as week-off / holiday / absent (never 'absent' in the future)."""
    first = date(year, month, 1)
    last = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    records = {a.date: a for a in Attendance.objects.filter(user=user, date__range=(first, last))}
    holidays = {h.date: h.name for h in Holiday.objects.filter(date__range=(first, last))}
    today = timezone.localdate()

    days, totals = [], {s.value: 0 for s in AttendanceStatus}
    total_minutes = 0
    cur = first
    while cur <= last:
        rec = records.get(cur)
        if rec:
            status = rec.status
            total_minutes += rec.working_minutes
            entry = {
                "date": cur.isoformat(), "status": status,
                "check_in": rec.check_in, "check_out": rec.check_out,
                "working_minutes": rec.working_minutes,
                "is_late": rec.is_late, "is_early_checkout": rec.is_early_checkout,
                "missing_checkout": rec.missing_checkout,
            }
        else:
            if cur in holidays:
                status = AttendanceStatus.HOLIDAY
            elif is_week_off(cur):
                status = AttendanceStatus.WEEK_OFF
            elif cur > today:
                status = None
            else:
                status = AttendanceStatus.ABSENT
            entry = {"date": cur.isoformat(), "status": status, "check_in": None,
                     "check_out": None, "working_minutes": 0, "is_late": False,
                     "is_early_checkout": False, "missing_checkout": False}
            if cur in holidays:
                entry["holiday"] = holidays[cur]
        if status:
            totals[status] = totals.get(status, 0) + 1
        days.append(entry)
        cur += timedelta(days=1)

    return {
        "year": year, "month": month, "days": days, "totals": totals,
        "total_hours": round(total_minutes / 60, 1),
    }


def today_summary(users):
    """Admin/manager 'today' tiles for a set of employees."""
    today = timezone.localdate()
    records = {a.user_id: a for a in Attendance.objects.filter(user__in=users, date=today)}
    counts = {"present": 0, "late": 0, "leave": 0, "absent": 0, "half_day": 0, "not_checked_in": 0}
    rows = []
    for u in users:
        rec = records.get(u.id)
        if rec:
            status = rec.status
            counts[status] = counts.get(status, 0) + 1
            if status in (AttendanceStatus.PRESENT, AttendanceStatus.LATE) and not rec.check_in:
                counts["not_checked_in"] += 1
        else:
            status = (AttendanceStatus.HOLIDAY if is_holiday(today)
                      else AttendanceStatus.WEEK_OFF if is_week_off(today)
                      else "not_checked_in")
            counts[status] = counts.get(status, 0) + 1
        rows.append({
            "user_id": u.id, "name": u.get_full_name() or u.username,
            "department": u.get_department_display(), "status": status,
            "check_in": rec.check_in if rec else None,
            "check_out": rec.check_out if rec else None,
            "working_minutes": rec.working_minutes if rec else 0,
        })
    return {"date": today.isoformat(), "counts": counts, "rows": rows}
