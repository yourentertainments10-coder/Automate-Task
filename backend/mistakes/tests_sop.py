"""The SOP register: the written process a mistake gets judged against."""
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User

from .models import SOP, Mistake


def make(username, role, department="accounts"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


SAMPLE = {
    "title": "Purchase invoice entry in Tally",
    "department": "accounts",
    "category": "Data Entry",
    "version": "v1",
    "steps": (
        "Collect the supplier invoice and the GRN for the same lot\n"
        "Check the invoice GST number against the supplier master\n"
        "Match every line item and rate against the purchase order\n"
        "Create the purchase voucher in Tally under the correct ledger\n"
        "Save the voucher and file the invoice in the month folder"
    ),
    "checks": (
        "Voucher total equals the invoice total to the paisa\n"
        "GST number on the voucher matches the invoice"
    ),
    "common_errors": (
        "Part name typed instead of the part code\n"
        "Rate taken from the quotation instead of the purchase order"
    ),
}


class SOPTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.staff = make("kesar", Role.ACCOUNTS)

    def as_(self, u):
        res = self.client.post("/api/auth/login",
                               {"username": u.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_manager_writes_a_process_and_everyone_can_read_it(self):
        self.as_(self.admin)
        res = self.client.post("/api/sops/", SAMPLE, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["step_count"], 5)

        self.as_(self.staff)                       # an employee can look it up
        rows = self.client.get("/api/sops/").data
        self.assertEqual(rows[0]["title"], SAMPLE["title"])

    def test_an_employee_cannot_rewrite_the_process(self):
        self.as_(self.staff)
        self.assertEqual(self.client.post("/api/sops/", SAMPLE, format="json").status_code, 403)

    def test_a_one_line_process_is_refused(self):
        self.as_(self.admin)
        res = self.client.post("/api/sops/", {**SAMPLE, "steps": "Do it properly"},
                               format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("steps", res.data)

    def test_a_new_version_supersedes_without_losing_the_old_one(self):
        self.as_(self.admin)
        sid = self.client.post("/api/sops/", SAMPLE, format="json").data["id"]
        res = self.client.post(f"/api/sops/{sid}/new_version/",
                               {"version": "v2",
                                "steps": SAMPLE["steps"] + "\nEmail the entry to the manager"},
                               format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["version"], "v2")
        self.assertEqual(res.data["step_count"], 6)
        self.assertFalse(SOP.objects.get(pk=sid).active)      # old one retired
        self.assertTrue(SOP.objects.filter(pk=sid).exists())  # but still there
        live = [s["version"] for s in self.client.get("/api/sops/").data]
        self.assertEqual(live, ["v2"])

    def test_removing_a_process_only_retires_it(self):
        self.as_(self.admin)
        sid = self.client.post("/api/sops/", SAMPLE, format="json").data["id"]
        self.assertEqual(self.client.delete(f"/api/sops/{sid}/").status_code, 204)
        self.assertTrue(SOP.objects.filter(pk=sid, active=False).exists())

    def test_a_mistake_can_cite_the_process_it_broke(self):
        self.as_(self.admin)
        sid = self.client.post("/api/sops/", SAMPLE, format="json").data["id"]
        m = Mistake.objects.create(employee=self.staff, category="Data Entry",
                                   description="Entered part name, not code",
                                   sop_id=sid)
        self.assertEqual(m.sop.title, SAMPLE["title"])
        self.assertEqual(SOP.objects.get(pk=sid).mistakes.count(), 1)

    def test_the_process_flattens_into_something_an_ai_can_compare(self):
        sop = SOP.objects.create(**SAMPLE)
        text = sop.as_prompt()
        for must in ("PROCESS:", "STEPS:", "CHECKS BEFORE DONE:", "KNOWN MISTAKES HERE:",
                     "Check the invoice GST number", "Part name typed instead"):
            self.assertIn(must, text)
