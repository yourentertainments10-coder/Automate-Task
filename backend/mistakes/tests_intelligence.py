"""Rules decide consequences; the AI only suggests. These tests prove the
register keeps working with the AI switched off — which is how it runs in
the suite, and how it must behave whenever a provider is down."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from crm.models import Task
from notifications.models import Notification

from . import intelligence as intel
from .models import SOP, Mistake, MistakeCategory, MistakeStatus


def make(username, role, department="accounts", manager=None):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department,
                                    reporting_manager=manager)


class RuleTests(TestCase):
    """No model involved: counting, escalation, the corrective task."""

    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.mgr = make("anurag", Role.ACCOUNTS_MANAGER)
        self.emp = make("kesar", Role.ACCOUNTS, manager=self.mgr)
        MistakeCategory.objects.create(name="Data Entry", active=True)

    def as_(self, u):
        r = self.client.post("/api/auth/login",
                             {"username": u.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

    def log_one(self, text="Part name typed instead of the part code"):
        self.as_(self.mgr)
        res = self.client.post("/api/mistakes/", {
            "employee": self.emp.id, "category": "Data Entry",
            "description": text, "severity": "medium"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return Mistake.objects.get(pk=res.data["id"])

    def test_first_mistake_spawns_a_corrective_task_for_the_employee(self):
        m = self.log_one()
        self.assertIsNotNone(m.corrective_task)
        task = m.corrective_task
        self.assertEqual(task.assigned_to, self.emp)
        self.assertIn("Correct:", task.title)
        self.assertTrue(Notification.objects.filter(
            user=self.emp, type="mistake_logged").exists())

    def test_first_time_is_not_escalated(self):
        m = self.log_one()
        self.assertEqual(m.occurrence_level, 1)     # first occurrence
        self.assertIsNone(m.repeat_of)
        self.assertEqual(m.escalation_level, 0)
        self.assertFalse(Notification.objects.filter(
            user=self.mgr, type="mistake_repeat").exists())

    def test_second_time_counts_as_a_repeat_and_asks_for_training(self):
        self.log_one()
        m2 = self.log_one("Wrong item name entered again")
        self.assertEqual(intel.occurrence_count(m2), 2)
        self.assertEqual(m2.occurrence_level, 1)    # a human confirms the link
        self.assertIsNone(m2.repeat_of)
        note = Notification.objects.get(user=self.mgr, type="mistake_repeat")
        self.assertIn("repeated", note.title)
        self.assertIn("2", note.body)

    def test_third_time_proposes_a_pip_without_imposing_one(self):
        self.log_one(); self.log_one("again"); m3 = self.log_one("third time")
        self.assertEqual(intel.occurrence_count(m3), 3)
        note = Notification.objects.filter(
            user=self.mgr, type="mistake_repeat").order_by("-id").first()
        self.assertIn("PIP", note.title)
        self.assertIn("the decision is yours", note.body)
        # nothing disciplinary is applied by the system itself
        self.assertEqual(m3.level3_action, "")

    def test_the_count_is_explainable_arithmetic(self):
        self.log_one(); m = self.log_one("again")
        self.assertEqual(intel.occurrence_count(m), 2)
        self.assertEqual(intel.escalation_for(1)["level"], 1)
        self.assertEqual(intel.escalation_for(2)["level"], 2)
        self.assertTrue(intel.escalation_for(3)["suggest_pip"])

    def test_a_stale_mistake_falls_out_of_the_window(self):
        old = self.log_one()
        Mistake.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=400))
        fresh = self.log_one("same thing much later")
        self.assertEqual(intel.occurrence_count(fresh), 1)


class SuggestionTests(TestCase):
    """With the AI off (as in the suite) every block degrades gracefully."""

    def setUp(self):
        self.client = APIClient()
        self.mgr = make("anurag", Role.ACCOUNTS_MANAGER)
        self.emp = make("kesar", Role.ACCOUNTS, manager=self.mgr)
        MistakeCategory.objects.create(name="Data Entry", active=True)
        self.m = Mistake.objects.create(
            employee=self.emp, manager=self.mgr, category="Data Entry",
            department="accounts",
            description="Part name typed instead of the part code in Tally")

    def as_(self, u):
        r = self.client.post("/api/auth/login",
                             {"username": u.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

    def test_suggestions_endpoint_works_with_the_ai_switched_off(self):
        self.as_(self.mgr)
        d = self.client.get(f"/api/mistakes/{self.m.id}/suggestions/").data
        self.assertEqual(d["occurrence"], 1)
        self.assertEqual(d["escalation"]["level"], 1)
        self.assertIsNone(d["category"])            # AI off
        self.assertIsNone(d["capa"])                # AI off
        self.assertIsInstance(d["similar"], list)   # word overlap still runs

    def test_similar_mistakes_are_found_by_wording_without_any_ai(self):
        Mistake.objects.create(employee=self.emp, category="Data Entry",
                               description="Typed the part name, not the code")
        found = intel.similar_past_mistakes(self.m)
        self.assertTrue(found)
        self.assertTrue(found[0]["same_person"])
        self.assertIn("part", found[0]["shared_words"])

    def test_no_written_process_means_no_verdict_not_a_guess(self):
        v = intel.judge_human_or_process(self.m)
        self.assertEqual(v["verdict"], "unclear")
        self.assertIn("No written process", v["reason"])
        self.assertEqual(v["provider"], "rules")

    def test_no_explanation_also_means_no_verdict(self):
        SOP.objects.create(title="Tally entry", department="accounts",
                           category="Data Entry", version="v1",
                           steps="Open the invoice\nEnter the part code")
        v = intel.judge_human_or_process(self.m)
        self.assertEqual(v["verdict"], "unclear")
        self.assertIn("not explained", v["reason"])

    def test_the_matching_process_is_picked_up_by_category(self):
        sop = SOP.objects.create(title="Tally entry", department="accounts",
                                 category="Data Entry", version="v1",
                                 steps="Open the invoice\nEnter the part code")
        self.assertEqual(intel.sop_for(self.m), sop)
