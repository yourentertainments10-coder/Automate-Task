from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from notifications.models import Notification

from .models import AssignmentRule, Lead, LeadStatus
from .reminders import send_followup_reminders


def make(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


class RoundRobinTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)
        self.amit = make("amit", Role.SALES_EXECUTIVE)
        self.priya = make("priya", Role.SALES_EXECUTIVE)
        self.rule = AssignmentRule.objects.create(
            department="sales", strategy="round_robin",
            member_ids=[self.rahul.pk, self.amit.pk, self.priya.pk],
        )
        res = self.client.post("/api/auth/login", {"username": "boss", "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def create(self, name):
        res = self.client.post("/api/leads/", {"customer_name": name, "department": "sales"})
        self.assertEqual(res.status_code, 201)
        return Lead.objects.get(pk=res.data["id"])

    def test_round_robin_sequence(self):
        # The requirement's exact example: 1->Rahul, 2->Amit, 3->Priya, 4->Rahul
        seq = [self.create(f"L{i}").assigned_to.username for i in range(1, 5)]
        self.assertEqual(seq, ["rahul", "amit", "priya", "rahul"])

    def test_auto_assign_notifies_and_logs(self):
        lead = self.create("Notified")
        n = Notification.objects.get(user=lead.assigned_to)
        self.assertEqual(n.type, "lead_assigned")
        events = self.client.get(f"/api/leads/{lead.pk}/events/").data
        self.assertTrue(any("Auto-assigned" in e["body"] for e in events))

    def test_inactive_member_is_skipped(self):
        self.amit.is_active = False
        self.amit.save()
        seq = [self.create(f"L{i}").assigned_to.username for i in range(1, 4)]
        self.assertEqual(seq, ["rahul", "priya", "rahul"])

    def test_fixed_strategy(self):
        self.rule.strategy = "fixed"
        self.rule.save()
        seq = [self.create(f"L{i}").assigned_to.username for i in range(1, 4)]
        self.assertEqual(seq, ["rahul", "rahul", "rahul"])

    def test_no_rule_leaves_unassigned(self):
        res = self.client.post("/api/leads/", {"customer_name": "P", "department": "purchase"})
        self.assertIsNone(Lead.objects.get(pk=res.data["id"]).assigned_to)

    def test_inactive_rule_leaves_unassigned(self):
        self.rule.active = False
        self.rule.save()
        lead = self.create("X")
        self.assertIsNone(lead.assigned_to)

    def test_manual_assignment_bypasses_rule_and_notifies(self):
        res = self.client.post("/api/leads/", {"customer_name": "Y", "assigned_to": self.priya.pk})
        lead = Lead.objects.get(pk=res.data["id"])
        self.assertEqual(lead.assigned_to, self.priya)
        self.assertEqual(self.rule.refresh_from_db() or AssignmentRule.objects.get(pk=self.rule.pk).rr_index, 0)
        self.assertTrue(Notification.objects.filter(user=self.priya, type="lead_assigned").exists())

    def test_rules_api_admin_only(self):
        c2 = APIClient()
        res = c2.post("/api/auth/login", {"username": "rahul", "password": "pass@12345"})
        c2.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        self.assertEqual(c2.get("/api/assignment-rules/").status_code, 403)
        self.assertEqual(self.client.get("/api/assignment-rules/").status_code, 200)

    def test_member_change_resets_rotation(self):
        self.create("A")  # rr_index -> 1
        res = self.client.patch(f"/api/assignment-rules/{self.rule.pk}/",
                                {"member_ids": [self.priya.pk, self.rahul.pk]}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["rr_index"], 0)
        self.assertEqual(self.create("B").assigned_to, self.priya)


class ReminderTests(TestCase):
    def setUp(self):
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)

    def lead(self, **kw):
        defaults = dict(customer_name="R", department="sales", assigned_to=self.rahul,
                        status=LeadStatus.CONTACTED)
        defaults.update(kw)
        return Lead.objects.create(**defaults)

    def test_due_lead_reminds_once(self):
        l = self.lead(follow_up_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(send_followup_reminders(), 1)
        self.assertEqual(send_followup_reminders(), 0)  # deduped
        self.assertEqual(Notification.objects.filter(user=self.rahul, type="follow_up_due").count(), 1)

    def test_rescheduled_follow_up_reminds_again(self):
        l = self.lead(follow_up_at=timezone.now() - timedelta(hours=2))
        send_followup_reminders()
        l.follow_up_at = timezone.now() + timedelta(seconds=1)
        l.save()
        import time
        time.sleep(1.1)
        self.assertEqual(send_followup_reminders(), 1)

    def test_future_or_closed_leads_are_ignored(self):
        self.lead(follow_up_at=timezone.now() + timedelta(days=1))
        self.lead(follow_up_at=timezone.now() - timedelta(days=1), status=LeadStatus.WON)
        self.lead(follow_up_at=None)
        self.assertEqual(send_followup_reminders(), 0)
