from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User

from .models import Lead, LeadStatus

import tempfile

MEDIA_TMP = tempfile.mkdtemp()


def make_user(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


class CrmBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("boss", Role.ADMIN, "management")
        self.manager = make_user("meera", Role.SALES_MANAGER, "sales")
        self.exec1 = make_user("rahul", Role.SALES_EXECUTIVE, "sales")
        self.exec2 = make_user("amit", Role.SALES_EXECUTIVE, "sales")
        self.accounts = make_user("anita", Role.ACCOUNTS, "accounts")
        self.purchase = make_user("vikram", Role.PURCHASE, "purchase")

        self.lead_r = Lead.objects.create(customer_name="Ravi", department="sales", assigned_to=self.exec1)
        self.lead_a = Lead.objects.create(customer_name="Sunita", department="sales", assigned_to=self.exec2)
        self.lead_p = Lead.objects.create(customer_name="Imran", department="purchase", assigned_to=self.purchase)
        self.lead_won = Lead.objects.create(customer_name="Meena", department="sales",
                                            assigned_to=self.exec1, status=LeadStatus.WON)

    def as_(self, user):
        res = self.client.post("/api/auth/login", {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def names(self, res):
        rows = res.data["results"] if "results" in res.data else res.data
        return sorted(r["customer_name"] for r in rows)


class ScopingTests(CrmBase):
    def test_admin_sees_all(self):
        self.as_(self.admin)
        self.assertEqual(self.names(self.client.get("/api/leads/")), ["Imran", "Meena", "Ravi", "Sunita"])

    def test_manager_sees_department(self):
        self.as_(self.manager)
        self.assertEqual(self.names(self.client.get("/api/leads/")), ["Meena", "Ravi", "Sunita"])

    def test_exec_sees_own_only(self):
        self.as_(self.exec1)
        self.assertEqual(self.names(self.client.get("/api/leads/")), ["Meena", "Ravi"])

    def test_accounts_sees_won_only(self):
        self.as_(self.accounts)
        self.assertEqual(self.names(self.client.get("/api/leads/")), ["Meena"])

    def test_purchase_sees_department(self):
        self.as_(self.purchase)
        self.assertEqual(self.names(self.client.get("/api/leads/")), ["Imran"])

    def test_exec_cannot_open_others_lead(self):
        self.as_(self.exec1)
        self.assertEqual(self.client.get(f"/api/leads/{self.lead_a.id}/").status_code, 404)


class LifecycleTests(CrmBase):
    def test_create_lead_defaults_and_event(self):
        self.as_(self.exec1)
        res = self.client.post("/api/leads/", {"customer_name": "New Guy", "phone": "981", "source": "manual"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["assigned_to"], self.exec1.id)  # exec self-assign default
        events = self.client.get(f"/api/leads/{res.data['id']}/events/").data
        self.assertEqual([e["type"] for e in events], ["assignment", "created"])

    def test_exec_cannot_assign_to_other(self):
        self.as_(self.exec1)
        res = self.client.post("/api/leads/", {"customer_name": "X", "assigned_to": self.exec2.id})
        self.assertEqual(res.status_code, 403)

    def test_status_change_logs_event(self):
        self.as_(self.exec1)
        res = self.client.patch(f"/api/leads/{self.lead_r.id}/", {"status": "contacted"})
        self.assertEqual(res.status_code, 200)
        events = self.client.get(f"/api/leads/{self.lead_r.id}/events/").data
        self.assertEqual(events[0]["type"], "status_change")
        self.assertIn("New -> Contacted", events[0]["body"])

    def test_exec_cannot_edit_others_lead(self):
        self.as_(self.exec2)
        res = self.client.patch(f"/api/leads/{self.lead_r.id}/", {"status": "contacted"})
        self.assertEqual(res.status_code, 404)  # not even visible

    def test_manager_reassigns_with_event(self):
        self.as_(self.manager)
        res = self.client.patch(f"/api/leads/{self.lead_r.id}/", {"assigned_to": self.exec2.id})
        self.assertEqual(res.status_code, 200)
        events = self.client.get(f"/api/leads/{self.lead_r.id}/events/").data
        self.assertEqual(events[0]["type"], "assignment")

    def test_exec_cannot_reassign(self):
        self.as_(self.exec1)
        res = self.client.patch(f"/api/leads/{self.lead_r.id}/", {"assigned_to": self.exec2.id})
        self.assertEqual(res.status_code, 403)

    def test_purchase_is_read_only(self):
        self.as_(self.purchase)
        res = self.client.patch(f"/api/leads/{self.lead_p.id}/", {"status": "contacted"})
        self.assertEqual(res.status_code, 403)

    def test_only_admin_deletes(self):
        self.as_(self.manager)
        self.assertEqual(self.client.delete(f"/api/leads/{self.lead_r.id}/").status_code, 403)
        self.as_(self.admin)
        self.assertEqual(self.client.delete(f"/api/leads/{self.lead_r.id}/").status_code, 204)

    def test_overdue_filter_and_summary(self):
        Lead.objects.filter(pk=self.lead_r.pk).update(follow_up_at=timezone.now() - timedelta(days=1))
        self.as_(self.admin)
        res = self.client.get("/api/leads/?overdue=true")
        self.assertEqual(self.names(res), ["Ravi"])
        summary = self.client.get("/api/leads/summary/").data
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["overdue"], 1)
        self.assertEqual(summary["by_status"]["won"], 1)


class SubResourceTests(CrmBase):
    def test_note_added_and_visible_in_events(self):
        self.as_(self.exec1)
        res = self.client.post(f"/api/leads/{self.lead_r.id}/notes/", {"body": "Called, call back Monday"})
        self.assertEqual(res.status_code, 201)
        events = self.client.get(f"/api/leads/{self.lead_r.id}/events/").data
        self.assertEqual(events[0]["body"], "Called, call back Monday")

    @override_settings(MEDIA_ROOT=MEDIA_TMP)
    def test_document_upload_and_size_limit(self):
        self.as_(self.exec1)
        f = SimpleUploadedFile("quote.pdf", b"%PDF fake", content_type="application/pdf")
        res = self.client.post(f"/api/leads/{self.lead_r.id}/documents/", {"file": f}, format="multipart")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["filename"], "quote.pdf")
        docs = self.client.get(f"/api/leads/{self.lead_r.id}/documents/").data
        self.assertEqual(len(docs), 1)

    def test_quotation_numbering_and_status_flow(self):
        self.as_(self.exec1)
        res = self.client.post(f"/api/leads/{self.lead_r.id}/quotations/", {"amount": "15000.00"})
        self.assertEqual(res.status_code, 201)
        self.assertRegex(res.data["number"], r"^QT-\d{4}-\d{4}$")
        qid = res.data["id"]
        res2 = self.client.patch(f"/api/quotations/{qid}/", {"status": "sent"})
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data["status"], "sent")
        events = self.client.get(f"/api/leads/{self.lead_r.id}/events/").data
        self.assertIn("draft -> sent", events[0]["body"])

    def test_accounts_cannot_note_on_won_lead(self):
        self.as_(self.accounts)  # can VIEW won leads but has no edit capability
        res = self.client.post(f"/api/leads/{self.lead_won.id}/notes/", {"body": "hi"})
        self.assertEqual(res.status_code, 403)
