from django.test import TestCase
from rest_framework.test import APIClient

from .models import DepartmentOption, Role, User


def make(username, role, password="pass@12345"):
    return User.objects.create_user(username, f"{username}@x.com", password, role=role)


class AuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN)
        self.exec_ = make("neha", Role.SALES_EXECUTIVE)

    def login(self, username, password="pass@12345"):
        res = self.client.post("/api/auth/login", {"username": username, "password": password})
        return res

    def auth(self, username):
        res = self.login(username)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        return res.data

    def test_login_ok_and_me(self):
        self.auth("boss")
        res = self.client.get("/api/auth/me")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["role"], "admin")
        self.assertIn("users.manage", res.data["capabilities"])

    def test_login_wrong_password(self):
        res = self.login("boss", "wrong")
        self.assertEqual(res.status_code, 401)

    def test_login_with_email_works(self):
        res = self.client.post("/api/auth/login",
                               {"username": "boss@x.com", "password": "pass@12345"})
        self.assertEqual(res.status_code, 200)
        # case-insensitive too
        res = self.client.post("/api/auth/login",
                               {"username": "BOSS@X.COM", "password": "pass@12345"})
        self.assertEqual(res.status_code, 200)

    def test_login_with_unknown_email_fails(self):
        res = self.client.post("/api/auth/login",
                               {"username": "nobody@x.com", "password": "pass@12345"})
        self.assertEqual(res.status_code, 401)

    def test_inactive_user_cannot_login(self):
        self.exec_.is_active = False
        self.exec_.save()
        self.assertEqual(self.login("neha").status_code, 401)

    def test_me_requires_auth(self):
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_refresh_and_logout_blacklist(self):
        tokens = self.auth("boss")
        res = self.client.post("/api/auth/refresh", {"refresh": tokens["refresh"]})
        self.assertEqual(res.status_code, 200)
        # rotated: logout with the NEW refresh, then it must be unusable
        new_refresh = res.data["refresh"]
        self.assertEqual(self.client.post("/api/auth/logout", {"refresh": new_refresh}).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/refresh", {"refresh": new_refresh}).status_code, 401)


class UserManagementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN)
        self.exec_ = make("neha", Role.SALES_EXECUTIVE)
        self.exec_.whatsapp_phone = "9876500000"
        self.exec_.reporting_manager = self.admin
        self.exec_.save(update_fields=["whatsapp_phone", "reporting_manager"])

    def as_(self, username):
        res = self.client.post("/api/auth/login", {"username": username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_non_admin_cannot_list_users(self):
        self.as_("neha")
        self.assertEqual(self.client.get("/api/users/").status_code, 403)

    def test_admin_creates_user_with_role(self):
        self.as_("boss")
        res = self.client.post("/api/users/", {
            "username": "sonal", "email": "sonal@x.com", "password": "sonal@12345",
            "role": "sales_manager", "department": "sales", "first_name": "Sonal",
            "whatsapp_phone": "9876543210", "reporting_manager": self.admin.id,
        })
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["role"], "sales_manager")
        self.assertIn("leads.assign", User.objects.get(username="sonal").role and res.data["capabilities"])

    def test_create_requires_contact_and_manager(self):
        """A blank email/phone silently drops that person's notifications and
        a blank "Reports to" sends their approvals to the admins, so all three
        are mandatory."""
        self.as_("boss")
        res = self.client.post("/api/users/", {
            "username": "gaps", "password": "sonal@12345",
            "role": "warehouse", "department": "warehouse",
        })
        self.assertEqual(res.status_code, 400)
        for field in ("email", "whatsapp_phone", "reporting_manager"):
            self.assertIn(field, res.data)

    def test_admin_needs_no_reporting_manager(self):
        self.as_("boss")
        res = self.client.post("/api/users/", {
            "username": "boss2", "email": "boss2@x.com", "password": "sonal@12345",
            "role": "admin", "department": "management",
            "whatsapp_phone": "9876543211",
        })
        self.assertEqual(res.status_code, 201)

    def test_phone_must_look_like_a_number(self):
        self.as_("boss")
        res = self.client.post("/api/users/", {
            "username": "badphone", "email": "b@x.com", "password": "sonal@12345",
            "role": "warehouse", "department": "warehouse",
            "whatsapp_phone": "12345", "reporting_manager": self.admin.id,
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("whatsapp_phone", res.data)

    def test_nobody_reports_to_themselves(self):
        self.as_("boss")
        res = self.client.patch(f"/api/users/{self.exec_.id}/",
                                {"reporting_manager": self.exec_.id})
        self.assertEqual(res.status_code, 400)
        self.assertIn("reporting_manager", res.data)

    def test_create_requires_password(self):
        self.as_("boss")
        res = self.client.post("/api/users/", {"username": "nopass", "role": "accounts"})
        self.assertEqual(res.status_code, 400)

    def test_weak_password_rejected(self):
        self.as_("boss")
        res = self.client.post("/api/users/", {"username": "weak", "password": "short", "role": "it_lead"})
        self.assertEqual(res.status_code, 400)

    def test_deactivate_and_activate(self):
        self.as_("boss")
        res = self.client.post(f"/api/users/{self.exec_.id}/deactivate/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(User.objects.get(pk=self.exec_.pk).is_active)
        res = self.client.post(f"/api/users/{self.exec_.id}/activate/")
        self.assertTrue(User.objects.get(pk=self.exec_.pk).is_active)

    def test_cannot_deactivate_self(self):
        self.as_("boss")
        self.assertEqual(self.client.post(f"/api/users/{self.admin.id}/deactivate/").status_code, 400)

    def test_delete_is_blocked(self):
        self.as_("boss")
        self.assertEqual(self.client.delete(f"/api/users/{self.exec_.id}/").status_code, 405)

    def test_admin_updates_role_without_password(self):
        self.as_("boss")
        res = self.client.patch(f"/api/users/{self.exec_.id}/", {"role": "it_lead"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["role"], "it_lead")
        # password unchanged -- login still works
        c2 = APIClient()
        self.assertEqual(c2.post("/api/auth/login", {"username": "neha", "password": "pass@12345"}).status_code, 200)


class DepartmentListTests(TestCase):
    """The department dropdown is data, not code: Admin can add/rename/remove
    it from Settings and every form picks the change up."""

    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN)
        self.emp = make("neha", Role.SALES_EXECUTIVE)

    def as_(self, username):
        res = self.client.post("/api/auth/login",
                               {"username": username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_everyone_reads_the_seeded_list(self):
        self.as_("neha")
        res = self.client.get("/api/departments/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("sales", [d["code"] for d in res.data])

    def test_only_admin_adds(self):
        self.as_("neha")
        self.assertEqual(self.client.post("/api/departments/",
                                          {"name": "Logistics"}).status_code, 403)
        self.as_("boss")
        res = self.client.post("/api/departments/", {"name": "Logistics"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["code"], "logistics")

    def test_a_user_can_be_put_in_a_brand_new_department(self):
        self.as_("boss")
        self.client.post("/api/departments/", {"name": "Logistics"})
        res = self.client.post("/api/users/", {
            "username": "logi", "email": "logi@x.com", "password": "sonal@12345",
            "role": "warehouse", "department": "logistics",
            "whatsapp_phone": "9876543210", "reporting_manager": self.admin.id,
        })
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(User.objects.get(username="logi").department, "logistics")

    def test_unknown_department_is_rejected(self):
        self.as_("boss")
        res = self.client.post("/api/users/", {
            "username": "ghost", "email": "g@x.com", "password": "sonal@12345",
            "role": "warehouse", "department": "does-not-exist",
            "whatsapp_phone": "9876543210", "reporting_manager": self.admin.id,
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("department", res.data)

    def test_rename_keeps_the_code(self):
        self.as_("boss")
        res = self.client.patch("/api/departments/support/", {"name": "IT & Systems"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["code"], "support")
        self.assertEqual(DepartmentOption.objects.get(code="support").name, "IT & Systems")

    def test_department_in_use_cannot_be_removed(self):
        self.as_("boss")
        res = self.client.delete("/api/departments/sales/")   # neha is in sales
        self.assertEqual(res.status_code, 400)
        self.assertTrue(DepartmentOption.objects.get(code="sales").active)

    def test_empty_department_is_removed_from_the_list(self):
        self.as_("boss")
        self.client.post("/api/departments/", {"name": "Logistics"})
        self.assertEqual(self.client.delete("/api/departments/logistics/").status_code, 200)
        codes = [d["code"] for d in self.client.get("/api/departments/").data]
        self.assertNotIn("logistics", codes)


class RoleWiringTests(TestCase):
    """A role lives in three places: the choices, the capability matrix and
    the assignment level. Miss one and the person is either uncreatable or
    silently gets the wrong access — so walk every role and check all three."""

    def test_every_role_has_capabilities(self):
        from .permissions import ROLE_CAPABILITIES
        missing = [r.value for r in Role if r not in ROLE_CAPABILITIES]
        self.assertEqual(missing, [],
                         f"roles with no entry in ROLE_CAPABILITIES: {missing}")

    def test_every_role_has_a_sane_assignment_level(self):
        from crm.scoping import ROLE_LEVEL, assignment_level
        for r in Role:
            lvl = ROLE_LEVEL.get(r, 1)
            self.assertIn(lvl, (1, 2, 3), f"{r.value} has level {lvl}")
        # a manager-sounding role must not silently sit at staff level
        for r in Role:
            if r.value.endswith("_manager") or r.value in ("admin", "it_lead"):
                self.assertGreaterEqual(
                    ROLE_LEVEL.get(r, 1), 2,
                    f"{r.value} looks senior but can only assign at staff level")

    def test_every_role_has_a_default_department(self):
        from .models import ROLE_DEFAULT_DEPARTMENT
        missing = [r.value for r in Role if r not in ROLE_DEFAULT_DEPARTMENT]
        self.assertEqual(missing, [],
                         f"roles with no default department: {missing}")

    def test_the_new_staff_roles_see_only_their_own_work(self):
        from .permissions import ROLE_CAPABILITIES
        for role in (Role.HOUSEKEEPING, Role.SECURITY, Role.LEGAL, Role.HR_EXECUTIVE):
            caps = ROLE_CAPABILITIES[role]
            self.assertEqual(caps, {"tasks.view_own", "notifications.view"},
                             f"{role.value} has more access than intended: {caps}")

    def test_a_user_can_actually_be_created_with_each_new_role(self):
        self.client = APIClient()
        res = self.client.post("/api/auth/login",
                               {"username": "boss", "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        for i, role in enumerate((Role.HOUSEKEEPING, Role.SECURITY,
                                  Role.LEGAL, Role.HR_EXECUTIVE)):
            r = self.client.post("/api/users/", {
                "username": f"new{i}", "email": f"new{i}@x.com",
                "password": "sonal@12345", "role": role.value,
                "department": "warehouse", "whatsapp_phone": f"98765432{i}0",
                "reporting_manager": self.admin.id})
            self.assertEqual(r.status_code, 201, f"{role.value}: {r.data}")

    def setUp(self):
        self.admin = make("boss", Role.ADMIN)


class RolesEndpointTests(TestCase):
    """The role dropdown used to be typed out again in the frontend, so the
    four roles added on 03 Sep existed in the backend but were missing from
    every form. The list now comes from here -- these tests are what stops it
    drifting again."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            "rolecheck", "rolecheck@x.com", "pass@12345",
            role=Role.SALES_EXECUTIVE, department="sales")
        res = self.client.post("/api/auth/login",
                               {"username": "rolecheck", "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_every_role_the_backend_accepts_is_offered(self):
        served = {r["value"] for r in self.client.get("/api/roles/").data}
        self.assertEqual(served, {value for value, _ in Role.choices})

    def test_the_roles_added_on_03_sep_are_there(self):
        served = {r["value"] for r in self.client.get("/api/roles/").data}
        for role in ("housekeeping", "security", "legal", "hr_executive"):
            self.assertIn(role, served)

    def test_manager_flag_matches_the_assignment_level(self):
        from crm.scoping import ROLE_LEVEL
        for row in self.client.get("/api/roles/").data:
            self.assertEqual(row["is_manager"], ROLE_LEVEL.get(row["value"], 1) >= 2,
                             f"{row['value']} disagrees with ROLE_LEVEL")

    def test_labels_are_human_readable(self):
        rows = self.client.get("/api/roles/").data
        by_value = {r["value"]: r["label"] for r in rows}
        self.assertEqual(by_value["security"], "Security")
        self.assertEqual(by_value["hr_executive"], "HR Executive")

    def test_signed_out_callers_get_nothing(self):
        self.client.credentials()
        self.assertEqual(self.client.get("/api/roles/").status_code, 401)


class ContactRequiredTests(TestCase):
    """Email was flatly required until 03 Sep 2026, when mail to a mailbox IT
    had not created yet bounced back to the sending account for weeks. A blank
    address now simply means "no mail" -- the same way a blank phone means no
    WhatsApp. Blanking BOTH is still refused: that person would never be told
    anything at all."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            "contact.boss", "boss@x.com", "pass@12345",
            role=Role.ADMIN, department="management")
        self.mgr = User.objects.create_user(
            "contact.mgr", "mgr@x.com", "pass@12345",
            role=Role.SALES_MANAGER, department="sales")
        res = self.client.post("/api/auth/login",
                               {"username": "contact.boss", "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def body(self, **over):
        return {"username": "newjoiner", "email": "new@x.com", "password": "pass@12345",
                "role": Role.SALES_EXECUTIVE, "department": "sales",
                "whatsapp_phone": "9711539878",
                "reporting_manager": self.mgr.id, **over}

    def test_a_joiner_with_no_mailbox_yet_can_be_created(self):
        res = self.client.post("/api/users/", self.body(email=""), format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(User.objects.get(username="newjoiner").email, "")

    def test_a_person_with_no_phone_still_needs_an_email(self):
        res = self.client.post("/api/users/", self.body(whatsapp_phone=""), format="json")
        self.assertEqual(res.status_code, 201, res.data)

    def test_blanking_both_is_refused(self):
        res = self.client.post("/api/users/",
                               self.body(email="", whatsapp_phone=""), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("email", res.data)

    def test_an_existing_address_can_be_cleared_when_it_bounces(self):
        """The actual fix for Jagdish: an admin can turn mail off themselves."""
        u = User.objects.create_user("bouncer", "dead@cartrends.in", "pass@12345",
                                     role=Role.SALES_EXECUTIVE, department="sales",
                                     whatsapp_phone="9711539878",
                                     reporting_manager=self.mgr)
        res = self.client.patch(f"/api/users/{u.id}/", {"email": ""}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        u.refresh_from_db()
        self.assertEqual(u.email, "")

    def test_clearing_the_last_channel_is_still_refused(self):
        u = User.objects.create_user("lastone", "x@y.com", "pass@12345",
                                     role=Role.SALES_EXECUTIVE, department="sales",
                                     whatsapp_phone="", reporting_manager=self.mgr)
        res = self.client.patch(f"/api/users/{u.id}/", {"email": ""}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_a_bad_phone_is_still_rejected(self):
        res = self.client.post("/api/users/", self.body(whatsapp_phone="12345"), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("whatsapp_phone", res.data)

    def test_no_mail_is_sent_to_a_blank_address(self):
        from notifications.channels.gmail import send_email
        out = send_email("", "subject", "body")
        self.assertEqual(out["status"], "skipped")
        self.assertIn("no email", out["detail"])
