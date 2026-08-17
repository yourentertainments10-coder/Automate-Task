from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User

from .models import Lead, LeadStatus


def make(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


class DashboardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.manager = make("meera", Role.SALES_MANAGER, "sales")
        self.exec_ = make("rahul", Role.SALES_EXECUTIVE, "sales")
        now = timezone.now()
        Lead.objects.create(customer_name="A", department="sales", assigned_to=self.exec_,
                            status=LeadStatus.NEW, source="whatsapp", estimated_value=1000)
        Lead.objects.create(customer_name="B", department="sales", assigned_to=self.exec_,
                            status=LeadStatus.WON, source="whatsapp", estimated_value=5000)
        Lead.objects.create(customer_name="C", department="sales", assigned_to=self.exec_,
                            status=LeadStatus.LOST, source="gmail")
        Lead.objects.create(customer_name="D", department="sales", assigned_to=self.exec_,
                            status=LeadStatus.CONTACTED, follow_up_at=now - timedelta(days=1),
                            estimated_value=2000, source="web")
        Lead.objects.create(customer_name="P", department="purchase", status=LeadStatus.NEW,
                            source="manual", estimated_value=700)

    def as_(self, username):
        res = self.client.post("/api/auth/login", {"username": username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_admin_tiles_cover_everything(self):
        self.as_("boss")
        t = self.client.get("/api/dashboard/").data["tiles"]
        self.assertEqual(t["total"], 5)
        self.assertEqual(t["new"], 2)
        self.assertEqual(t["active"], 3)          # A, D, P
        self.assertEqual(t["won"], 1)
        self.assertEqual(t["lost"], 1)
        self.assertEqual(t["overdue"], 1)         # D
        self.assertEqual(t["conversion_pct"], 50)
        self.assertEqual(t["pipeline_value"], 3700.0)  # 1000 + 2000 + 700

    def test_manager_scoped_to_department(self):
        self.as_("meera")
        data = self.client.get("/api/dashboard/").data
        self.assertEqual(data["tiles"]["total"], 4)  # not the purchase lead
        sources = {s["source"]: s for s in data["sources"]}
        self.assertNotIn("manual", sources)

    def test_employee_and_source_breakdowns(self):
        self.as_("boss")
        data = self.client.get("/api/dashboard/").data
        rahul = next(e for e in data["employees"] if e["name"] == "rahul")
        self.assertEqual(rahul["total"], 4)
        self.assertEqual(rahul["won"], 1)
        self.assertEqual(rahul["overdue"], 1)
        wa = next(s for s in data["sources"] if s["source"] == "whatsapp")
        self.assertEqual(wa["total"], 2)
        self.assertEqual(wa["conversion_pct"], 50)

    def test_per_day_has_14_days_and_todays_count(self):
        self.as_("boss")
        per_day = self.client.get("/api/dashboard/").data["per_day"]
        self.assertEqual(len(per_day), 14)
        self.assertEqual(per_day[-1]["count"], 5)  # all created today

    def test_executive_gets_403(self):
        self.as_("rahul")
        self.assertEqual(self.client.get("/api/dashboard/").status_code, 403)
