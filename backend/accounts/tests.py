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
