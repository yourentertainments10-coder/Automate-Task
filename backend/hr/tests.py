from datetime import date, timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from crm.models import Holiday

from . import services
from .models import (
    Attendance, AttendanceCorrection, FaceProfile, LeaveRequest, LeaveType,
    OfficeLocation,
)

# Gurugram-ish office + a point ~1.1 km away
OFFICE = (28.4595, 77.0266)
FAR = (28.4695, 77.0266)


def make(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


class Base(TestCase):
    def setUp(self):
        # Tests must not inherit whatever flags the developer has in .env --
        # each feature test switches its own flag on explicitly.
        import os
        os.environ["FACE_RECOGNITION_ENABLED"] = "false"
        os.environ["GEOFENCE_ENABLED"] = "false"
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.manager = make("meera", Role.SALES_MANAGER)
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)
        self.amit = make("amit", Role.SALES_EXECUTIVE)
        self.vikram = make("vikram", Role.PURCHASE, "purchase")

    def as_(self, user):
        res = self.client.post("/api/auth/login", {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")


class GeoFenceTests(Base):
    def setUp(self):
        super().setUp()
        OfficeLocation.objects.create(name="HQ", latitude=OFFICE[0], longitude=OFFICE[1], radius_m=200)

    def test_haversine_is_sane(self):
        d = services.haversine_m(*OFFICE, *FAR)
        self.assertTrue(1000 < d < 1200, d)
        self.assertEqual(int(services.haversine_m(*OFFICE, *OFFICE)), 0)

    @override_settings()
    def test_disabled_geofence_allows_any_location(self):
        import os
        os.environ["GEOFENCE_ENABLED"] = "false"
        self.as_(self.rahul)
        res = self.client.post("/api/attendance/check_in/",
                               {"latitude": FAR[0], "longitude": FAR[1]}, format="json")
        self.assertEqual(res.status_code, 201)

    def test_enabled_geofence_blocks_far_and_allows_near(self):
        import os
        os.environ["GEOFENCE_ENABLED"] = "true"
        try:
            self.as_(self.rahul)
            res = self.client.post("/api/attendance/check_in/",
                                   {"latitude": FAR[0], "longitude": FAR[1]}, format="json")
            self.assertEqual(res.status_code, 400)
            self.assertIn("from HQ", res.data["detail"])
            self.assertEqual(Attendance.objects.count(), 0)
            # missing coords are refused too
            res = self.client.post("/api/attendance/check_in/", {}, format="json")
            self.assertEqual(res.status_code, 400)
            # inside the fence works
            res = self.client.post("/api/attendance/check_in/",
                                   {"latitude": OFFICE[0], "longitude": OFFICE[1]}, format="json")
            self.assertEqual(res.status_code, 201)
            self.assertEqual(Attendance.objects.get().location.name, "HQ")
        finally:
            os.environ["GEOFENCE_ENABLED"] = "false"

    def test_office_crud_is_admin_only(self):
        self.as_(self.manager)
        self.assertEqual(self.client.get("/api/office-locations/").status_code, 200)
        res = self.client.post("/api/office-locations/",
                               {"name": "Branch", "latitude": 1, "longitude": 1})
        self.assertEqual(res.status_code, 403)
        self.as_(self.admin)
        self.assertEqual(self.client.post("/api/office-locations/",
                                          {"name": "Branch", "latitude": 1, "longitude": 1}).status_code, 201)
        bad = self.client.post("/api/office-locations/",
                               {"name": "Bad", "latitude": 999, "longitude": 1})
        self.assertEqual(bad.status_code, 400)


class FaceTests(Base):
    def enable(self, value="true", self_enroll="false"):
        import os
        os.environ["FACE_RECOGNITION_ENABLED"] = value
        os.environ["FACE_SELF_ENROLL"] = self_enroll

    def tearDown(self):
        import os
        os.environ["FACE_RECOGNITION_ENABLED"] = "false"
        os.environ.pop("FACE_SELF_ENROLL", None)

    def test_enrolment_is_admin_only_and_validated(self):
        self.as_(self.manager)
        self.assertEqual(self.client.post(f"/api/hr/face/{self.rahul.id}/",
                                          {"descriptor": [0.1] * 64}, format="json").status_code, 403)
        self.as_(self.admin)
        self.assertEqual(self.client.post(f"/api/hr/face/{self.rahul.id}/",
                                          {"descriptor": [0.1] * 4}, format="json").status_code, 400)
        res = self.client.post(f"/api/hr/face/{self.rahul.id}/",
                               {"descriptor": [0.1] * 64}, format="json")
        self.assertEqual(res.status_code, 201 if res.status_code == 201 else 200)
        self.assertTrue(FaceProfile.objects.filter(user=self.rahul).exists())
        self.client.delete(f"/api/hr/face/{self.rahul.id}/")
        self.assertFalse(FaceProfile.objects.filter(user=self.rahul).exists())

    def test_unenrolled_user_cannot_mark_when_face_required(self):
        self.enable()
        self.as_(self.rahul)
        res = self.client.post("/api/attendance/check_in/", {}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("not enrolled", res.data["detail"])

    def test_mismatch_never_marks_attendance(self):
        self.enable()
        FaceProfile.objects.create(user=self.rahul, descriptor=[0.0] * 64)
        self.as_(self.rahul)
        res = self.client.post("/api/attendance/check_in/",
                               {"face_descriptor": [1.0] * 64}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("did not match", res.data["detail"])
        self.assertEqual(Attendance.objects.count(), 0)

    def test_matching_face_marks_and_records_confidence(self):
        self.enable()
        FaceProfile.objects.create(user=self.rahul, descriptor=[0.0] * 64)
        self.as_(self.rahul)
        res = self.client.post("/api/attendance/check_in/",
                               {"face_descriptor": [0.01] * 64}, format="json")
        self.assertEqual(res.status_code, 201)
        rec = Attendance.objects.get()
        self.assertTrue(rec.face_verified)
        self.assertGreater(rec.face_confidence, 0.9)

    def test_self_enrolment_first_capture_becomes_profile(self):
        from notifications.models import Notification
        self.enable(self_enroll="true")
        self.as_(self.rahul)
        # First check-in with no profile: enrols AND marks attendance
        res = self.client.post("/api/attendance/check_in/",
                               {"face_descriptor": [0.2] * 64}, format="json")
        self.assertEqual(res.status_code, 201)
        profile = FaceProfile.objects.get(user=self.rahul)
        self.assertIsNone(profile.enrolled_by)          # None = self-enrolled
        self.assertTrue(Attendance.objects.get().face_verified)
        # HR/Admin got told about it
        self.assertTrue(Notification.objects.filter(type="face_enrolled",
                                                    user=self.admin).exists())
        # Check-out with a DIFFERENT face must now fail — profile is locked in
        res = self.client.post("/api/attendance/check_out/",
                               {"face_descriptor": [0.9] * 64}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("did not match", res.data["detail"])
        # ...and with the same face it succeeds
        res = self.client.post("/api/attendance/check_out/",
                               {"face_descriptor": [0.21] * 64}, format="json")
        self.assertIn(res.status_code, (200, 201))

    def test_self_enrolment_off_keeps_old_behaviour(self):
        self.enable(self_enroll="false")
        self.as_(self.rahul)
        res = self.client.post("/api/attendance/check_in/",
                               {"face_descriptor": [0.2] * 64}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("not enrolled", res.data["detail"])
        self.assertFalse(FaceProfile.objects.filter(user=self.rahul).exists())

    def test_reset_then_fresh_self_enrolment(self):
        """HR resets a broken profile; the employee's next capture re-enrols."""
        self.enable(self_enroll="true")
        FaceProfile.objects.create(user=self.rahul, descriptor=[0.9] * 64)
        self.as_(self.admin)
        self.client.delete(f"/api/hr/face/{self.rahul.id}/")
        self.as_(self.rahul)
        res = self.client.post("/api/attendance/check_in/",
                               {"face_descriptor": [0.1] * 64}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(FaceProfile.objects.get(user=self.rahul).descriptor[0], 0.1)


class ManualMarkTests(Base):
    def test_hr_marks_present_with_audit_note(self):
        self.as_(self.admin)
        res = self.client.post("/api/attendance/manual_mark/",
                               {"user": self.rahul.id, "status": "present",
                                "reason": "face lock not working"}, format="json")
        self.assertEqual(res.status_code, 200)
        rec = Attendance.objects.get(user=self.rahul)
        self.assertEqual(rec.status, "present")
        self.assertIn("Marked present by", rec.note)
        self.assertIn("face lock not working", rec.note)

    def test_manager_cannot_manual_mark(self):
        self.as_(self.manager)   # hr.approve but not hr.manage
        res = self.client.post("/api/attendance/manual_mark/",
                               {"user": self.rahul.id}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_future_date_and_bad_status_rejected(self):
        self.as_(self.admin)
        future = (timezone.localdate() + timedelta(days=2)).isoformat()
        self.assertEqual(self.client.post("/api/attendance/manual_mark/",
                                          {"user": self.rahul.id, "date": future},
                                          format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/attendance/manual_mark/",
                                          {"user": self.rahul.id, "status": "leave"},
                                          format="json").status_code, 400)


class AttendanceFlowTests(Base):
    def test_check_in_out_computes_hours_and_blocks_duplicates(self):
        self.as_(self.rahul)
        res = self.client.post("/api/attendance/check_in/", {}, format="json")
        self.assertEqual(res.status_code, 201)
        dup = self.client.post("/api/attendance/check_in/", {}, format="json")
        self.assertEqual(dup.status_code, 400)
        self.assertIn("already checked in", dup.data["detail"])

        rec = Attendance.objects.get()
        rec.check_in = timezone.now() - timedelta(hours=9)
        rec.save()
        res = self.client.post("/api/attendance/check_out/", {}, format="json")
        self.assertEqual(res.status_code, 200 if res.status_code == 200 else 201)
        rec.refresh_from_db()
        self.assertGreaterEqual(rec.working_minutes, 8 * 60)
        self.assertIn(rec.status, ("present", "late"))
        self.assertEqual(self.client.post("/api/attendance/check_out/", {}, format="json").status_code, 400)

    def test_checkout_without_checkin_rejected(self):
        self.as_(self.rahul)
        res = self.client.post("/api/attendance/check_out/", {}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("not checked in", res.data["detail"])

    def test_short_day_is_half_day(self):
        self.as_(self.rahul)
        self.client.post("/api/attendance/check_in/", {}, format="json")
        rec = Attendance.objects.get()
        rec.check_in = timezone.now() - timedelta(hours=2)
        rec.save()
        self.client.post("/api/attendance/check_out/", {}, format="json")
        rec.refresh_from_db()
        self.assertEqual(rec.status, "half_day")

    def test_today_endpoint_flags(self):
        self.as_(self.rahul)
        data = self.client.get("/api/attendance/today/").data
        self.assertTrue(data["can_check_in"])
        self.assertFalse(data["can_check_out"])
        self.client.post("/api/attendance/check_in/", {}, format="json")
        data = self.client.get("/api/attendance/today/").data
        self.assertFalse(data["can_check_in"])
        self.assertTrue(data["can_check_out"])

    def test_history_scoping(self):
        Attendance.objects.create(user=self.rahul, date=date(2026, 8, 3))
        Attendance.objects.create(user=self.amit, date=date(2026, 8, 3))
        Attendance.objects.create(user=self.vikram, date=date(2026, 8, 3))
        self.as_(self.rahul)
        rows = self.client.get("/api/attendance/").data["results"]
        self.assertEqual({r["user"] for r in rows}, {self.rahul.id})
        self.as_(self.manager)  # department scope
        rows = self.client.get("/api/attendance/?scope=team").data["results"]
        self.assertEqual({r["user"] for r in rows}, {self.rahul.id, self.amit.id})
        self.as_(self.admin)
        rows = self.client.get("/api/attendance/?scope=team").data["results"]
        self.assertEqual(len(rows), 3)

    def test_cannot_view_other_employee_month(self):
        self.as_(self.rahul)
        res = self.client.get(f"/api/attendance/monthly/?user={self.amit.id}")
        self.assertEqual(res.status_code, 403)
        self.as_(self.manager)
        self.assertEqual(self.client.get(f"/api/attendance/monthly/?user={self.rahul.id}").status_code, 200)

    def test_monthly_report_classifies_days(self):
        Holiday.objects.create(name="Independence Day", date=date(2026, 8, 15))
        Attendance.objects.create(user=self.rahul, date=date(2026, 8, 3),
                                  status="present", working_minutes=540)
        report = services.monthly_report(self.rahul, 2026, 8)
        self.assertEqual(len(report["days"]), 31)
        by_date = {d["date"]: d for d in report["days"]}
        self.assertEqual(by_date["2026-08-03"]["status"], "present")
        self.assertEqual(by_date["2026-08-15"]["status"], "holiday")
        self.assertEqual(by_date["2026-08-02"]["status"], "week_off")   # Sunday
        self.assertEqual(by_date["2026-08-04"]["status"], "absent")
        self.assertEqual(report["totals"]["present"], 1)
        self.assertEqual(report["total_hours"], 9.0)

    def test_team_today_needs_capability(self):
        self.as_(self.rahul)
        self.assertEqual(self.client.get("/api/attendance/team_today/").status_code, 403)
        self.as_(self.manager)
        data = self.client.get("/api/attendance/team_today/").data
        self.assertEqual({r["user_id"] for r in data["rows"]}, {self.rahul.id, self.amit.id, self.manager.id})


class CorrectionTests(Base):
    def test_request_review_and_attendance_update(self):
        day = timezone.localdate() - timedelta(days=1)
        self.as_(self.rahul)
        res = self.client.post("/api/attendance-corrections/", {
            "date": day.isoformat(),
            "requested_check_in": f"{day}T09:30:00Z",
            "requested_check_out": f"{day}T18:30:00Z",
            "reason": "Forgot to check out",
        }, format="json")
        self.assertEqual(res.status_code, 201)
        cid = res.data["id"]
        # employee cannot approve their own
        self.assertEqual(self.client.post(f"/api/attendance-corrections/{cid}/review/",
                                          {"decision": "approved"}).status_code, 403)
        self.as_(self.manager)
        res = self.client.post(f"/api/attendance-corrections/{cid}/review/",
                               {"decision": "approved", "remarks": "OK"})
        self.assertEqual(res.status_code, 200)
        rec = Attendance.objects.get(user=self.rahul, date=day)
        self.assertEqual(rec.working_minutes, 540)
        self.assertEqual(rec.status, "present")
        # double review blocked
        self.assertEqual(self.client.post(f"/api/attendance-corrections/{cid}/review/",
                                          {"decision": "rejected"}).status_code, 400)

    def test_correction_requires_a_time(self):
        self.as_(self.rahul)
        res = self.client.post("/api/attendance-corrections/",
                               {"date": "2026-08-03", "reason": "x"}, format="json")
        self.assertEqual(res.status_code, 400)


class LeaveTests(Base):
    def setUp(self):
        super().setUp()
        self.casual = LeaveType.objects.create(name="Casual", annual_quota=12)
        self.medical = LeaveType.objects.create(name="Medical", annual_quota=6,
                                                requires_document=True)

    def apply(self, start, end, ltype=None):
        return self.client.post("/api/leaves/", {
            "leave_type": (ltype or self.casual).id,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "reason": "Family function",
        }, format="json")

    def test_apply_counts_working_days_only(self):
        Holiday.objects.create(name="Holiday", date=date(2026, 9, 2))
        self.as_(self.rahul)
        res = self.apply(date(2026, 8, 31), date(2026, 9, 6))  # Mon..Sun
        self.assertEqual(res.status_code, 201)
        # 31 Aug + 1,3,4 Sep (2 Sep holiday, 5-6 Sat/Sun -> Sunday only off) = 5 working days
        self.assertEqual(LeaveRequest.objects.get().days, 5)

    def test_invalid_range_and_overlap_and_document(self):
        self.as_(self.rahul)
        bad = self.apply(date(2026, 9, 10), date(2026, 9, 1))
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.apply(date(2026, 9, 1), date(2026, 9, 3)).status_code, 201)
        self.assertEqual(self.apply(date(2026, 9, 2), date(2026, 9, 4)).status_code, 400)  # overlap
        res = self.apply(date(2026, 10, 1), date(2026, 10, 2), self.medical)
        self.assertEqual(res.status_code, 400)  # document required

    def test_approval_writes_leave_into_attendance_and_notifies(self):
        from notifications.models import Notification
        self.as_(self.rahul)
        lid = self.apply(date(2026, 9, 1), date(2026, 9, 2)).data["id"]
        self.as_(self.manager)
        res = self.client.post(f"/api/leaves/{lid}/review/",
                               {"decision": "approved", "remarks": "Approved"})
        self.assertEqual(res.status_code, 200)
        days = Attendance.objects.filter(user=self.rahul, status="leave").count()
        self.assertEqual(days, 2)
        self.assertTrue(Notification.objects.filter(user=self.rahul, type="leave_reviewed").exists())

    def test_rejection_leaves_attendance_untouched(self):
        self.as_(self.rahul)
        lid = self.apply(date(2026, 9, 1), date(2026, 9, 2)).data["id"]
        self.as_(self.manager)
        self.client.post(f"/api/leaves/{lid}/review/", {"decision": "rejected", "remarks": "Peak season"})
        self.assertEqual(Attendance.objects.filter(status="leave").count(), 0)

    def test_cancel_pending_and_revoke_approved(self):
        self.as_(self.rahul)
        lid = self.apply(date(2026, 9, 1), date(2026, 9, 2)).data["id"]
        res = self.client.post(f"/api/leaves/{lid}/cancel/")
        self.assertEqual(res.data["status"], "cancelled")
        lid2 = self.apply(date(2026, 12, 1), date(2026, 12, 2)).data["id"]
        self.as_(self.manager)
        self.client.post(f"/api/leaves/{lid2}/review/", {"decision": "approved"})
        self.assertEqual(Attendance.objects.filter(status="leave").count(), 2)
        self.as_(self.rahul)
        self.client.post(f"/api/leaves/{lid2}/cancel/")
        self.assertEqual(Attendance.objects.filter(status="leave").count(), 0)

    def test_balance_reflects_approved_leave(self):
        self.as_(self.rahul)
        lid = self.apply(date(timezone.localdate().year, 9, 1),
                         date(timezone.localdate().year, 9, 2)).data["id"]
        bal = {b["name"]: b for b in self.client.get("/api/leaves/balances/").data}
        self.assertEqual(bal["Casual"]["balance"], 12)
        self.assertEqual(bal["Casual"]["pending"], 2)
        self.as_(self.manager)
        self.client.post(f"/api/leaves/{lid}/review/", {"decision": "approved"})
        self.as_(self.rahul)
        bal = {b["name"]: b for b in self.client.get("/api/leaves/balances/").data}
        self.assertEqual((bal["Casual"]["used"], bal["Casual"]["balance"]), (2, 10))

    def test_scoping_and_review_permissions(self):
        self.as_(self.rahul)
        lid = self.apply(date(2026, 9, 1), date(2026, 9, 2)).data["id"]
        self.as_(self.amit)
        self.assertEqual(len(self.client.get("/api/leaves/").data["results"]), 0)
        self.assertEqual(self.client.post(f"/api/leaves/{lid}/review/",
                                          {"decision": "approved"}).status_code, 403)
        self.as_(self.vikram)  # purchase manager-less user, different department
        self.assertEqual(self.client.post(f"/api/leaves/{lid}/review/",
                                          {"decision": "approved"}).status_code, 403)
        self.as_(self.manager)
        team = self.client.get("/api/leaves/?scope=team").data["results"]
        self.assertEqual(len(team), 1)

    def test_leave_types_admin_only_write(self):
        self.as_(self.manager)
        self.assertEqual(self.client.post("/api/leave-types/", {"name": "Comp Off"}).status_code, 403)
        self.as_(self.admin)
        self.assertEqual(self.client.post("/api/leave-types/", {"name": "Comp Off"}).status_code, 201)

    def test_check_in_blocked_on_approved_leave(self):
        today = timezone.localdate()
        leave = LeaveRequest.objects.create(user=self.rahul, leave_type=self.casual,
                                            start_date=today, end_date=today, days=1,
                                            reason="x", status="approved")
        services.apply_leave_to_attendance(leave)
        self.as_(self.rahul)
        res = self.client.post("/api/attendance/check_in/", {}, format="json")
        if not services.is_week_off(today) and not services.is_holiday(today):
            self.assertEqual(res.status_code, 400)
            self.assertIn("approved leave", res.data["detail"])


class ConfigTests(Base):
    def test_config_exposes_flags_and_capabilities(self):
        self.as_(self.rahul)
        data = self.client.get("/api/hr/config/").data
        self.assertFalse(data["can_approve"])
        self.assertFalse(data["can_manage"])
        self.assertIn("geofence_enabled", data)
        self.as_(self.manager)
        self.assertTrue(self.client.get("/api/hr/config/").data["can_approve"])
        self.as_(self.admin)
        self.assertTrue(self.client.get("/api/hr/config/").data["can_manage"])
