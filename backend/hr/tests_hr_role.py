"""Separation of duties: the dedicated HR Manager role, and the rule that
nobody -- admin included -- approves their own leave/attendance request.
"""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from crm.models import Lead

from .models import AttendanceCorrection, LeaveRequest, LeaveType


def make(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


class Base(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.hr = make("neha", Role.HR_MANAGER, "hr")
        self.manager = make("meera", Role.SALES_MANAGER)
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)
        self.casual = LeaveType.objects.create(name="Casual", annual_quota=12)

    def as_(self, user):
        res = self.client.post("/api/auth/login", {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def leave_for(self, user, start=date(2026, 9, 1), end=date(2026, 9, 2)):
        return LeaveRequest.objects.create(user=user, leave_type=self.casual,
                                           start_date=start, end_date=end, days=2,
                                           reason="Personal")

    def correction_for(self, user):
        day = timezone.localdate() - timedelta(days=1)
        return AttendanceCorrection.objects.create(
            user=user, date=day, reason="Forgot to check out",
            requested_check_out=timezone.now())


class HrManagerRoleTests(Base):
    def test_capabilities(self):
        self.as_(self.hr)
        me = self.client.get("/api/auth/me").data
        self.assertEqual(me["role_display"], "HR Manager")
        caps = set(me["capabilities"])
        self.assertIn("hr.manage", caps)
        self.assertIn("hr.approve", caps)
        self.assertIn("users.manage", caps)
        # No sales access whatsoever
        self.assertFalse({c for c in caps if c.startswith("leads.")})
        self.assertNotIn("dashboard.view", caps)

    def test_hr_manager_sees_no_leads_and_no_sales_dashboard(self):
        Lead.objects.create(customer_name="Ravi", department="sales", assigned_to=self.rahul)
        self.as_(self.hr)
        self.assertEqual(len(self.client.get("/api/leads/").data["results"]), 0)
        self.assertEqual(self.client.get("/api/dashboard/").status_code, 403)

    def test_hr_manager_approves_across_all_departments(self):
        leave = self.leave_for(self.rahul)
        self.as_(self.hr)
        res = self.client.post(f"/api/leaves/{leave.id}/review/",
                               {"decision": "approved", "remarks": "OK"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "approved")
        self.assertEqual(res.data["reviewed_by_detail"]["username"], "neha")

    def test_hr_manager_can_manage_users_and_hr_settings(self):
        self.as_(self.hr)
        self.assertEqual(self.client.get("/api/users/").status_code, 200)
        self.assertEqual(self.client.post("/api/leave-types/",
                                          {"name": "Comp Off"}).status_code, 201)
        self.assertEqual(self.client.post("/api/office-locations/",
                                          {"name": "HQ", "latitude": 28.4, "longitude": 77.0}).status_code, 201)

    def test_hr_manager_cannot_escalate_to_admin(self):
        self.as_(self.hr)
        # cannot create an admin
        res = self.client.post("/api/users/", {"username": "sneaky", "password": "sneaky@12345",
                                               "role": "admin", "department": "management"})
        self.assertEqual(res.status_code, 403)
        # cannot promote an existing user to admin
        self.assertEqual(self.client.patch(f"/api/users/{self.rahul.id}/",
                                           {"role": "admin"}).status_code, 403)
        # cannot edit or deactivate an admin account
        self.assertEqual(self.client.patch(f"/api/users/{self.admin.id}/",
                                           {"first_name": "X"}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/users/{self.admin.id}/deactivate/").status_code, 403)
        # cannot change their own role
        self.assertEqual(self.client.patch(f"/api/users/{self.hr.id}/",
                                           {"role": "sales_manager"}).status_code, 403)
        # but ordinary onboarding still works
        res = self.client.post("/api/users/", {
            "username": "newjoinee", "password": "newjoin@12345",
            "role": "sales_executive", "department": "sales",
            # email / phone / reports-to are mandatory now
            "email": "newjoinee@x.com", "whatsapp_phone": "9876543210",
            "reporting_manager": self.hr.id})
        self.assertEqual(res.status_code, 201)
        # ...and an Admin is still free to grant the admin role
        self.as_(self.admin)
        self.assertEqual(self.client.patch(f"/api/users/{self.rahul.id}/",
                                           {"role": "admin"}).status_code, 200)

    def test_sales_manager_still_limited_to_own_department(self):
        outsider = make("vikram", Role.PURCHASE, "purchase")
        leave = self.leave_for(outsider)
        self.as_(self.manager)
        self.assertEqual(self.client.post(f"/api/leaves/{leave.id}/review/",
                                          {"decision": "approved"}).status_code, 403)


class SelfApprovalTests(Base):
    def test_admin_cannot_approve_own_leave(self):
        leave = self.leave_for(self.admin)
        self.as_(self.admin)
        res = self.client.post(f"/api/leaves/{leave.id}/review/", {"decision": "approved"})
        self.assertEqual(res.status_code, 403)
        self.assertIn("cannot approve your own request", res.data["detail"])
        leave.refresh_from_db()
        self.assertEqual(leave.status, "pending")

    def test_admin_cannot_approve_own_correction(self):
        correction = self.correction_for(self.admin)
        self.as_(self.admin)
        res = self.client.post(f"/api/attendance-corrections/{correction.id}/review/",
                               {"decision": "approved"})
        self.assertEqual(res.status_code, 403)
        correction.refresh_from_db()
        self.assertEqual(correction.status, "pending")

    def test_hr_manager_cannot_approve_own_leave(self):
        leave = self.leave_for(self.hr)
        self.as_(self.hr)
        res = self.client.post(f"/api/leaves/{leave.id}/review/", {"decision": "approved"})
        self.assertEqual(res.status_code, 403)

    def test_someone_else_can_approve_the_admins_leave(self):
        leave = self.leave_for(self.admin)
        self.as_(self.hr)
        res = self.client.post(f"/api/leaves/{leave.id}/review/",
                               {"decision": "approved", "remarks": "Approved by HR"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["reviewed_by_detail"]["username"], "neha")

    def test_message_names_the_available_approvers(self):
        leave = self.leave_for(self.admin)
        self.as_(self.admin)
        detail = self.client.post(f"/api/leaves/{leave.id}/review/",
                                  {"decision": "approved"}).data["detail"]
        self.assertIn("neha", detail)      # HR manager is a valid approver
        self.assertIn("meera", detail)     # so is the sales manager

    def test_message_when_no_other_approver_exists(self):
        self.hr.is_active = False
        self.hr.save()
        self.manager.is_active = False
        self.manager.save()
        leave = self.leave_for(self.admin)
        self.as_(self.admin)
        detail = self.client.post(f"/api/leaves/{leave.id}/review/",
                                  {"decision": "approved"}).data["detail"]
        self.assertIn("No other approver exists", detail)
        self.assertIn("add an HR Manager", detail)
