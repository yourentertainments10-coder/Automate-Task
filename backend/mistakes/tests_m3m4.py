"""M3 (AI suggest, patterns, founder view, digests) + M4 (scoring)."""
from datetime import timedelta

from django.utils import timezone

from crm.models import Task, TaskStatus
from notifications.models import Notification

from .ai import suggest
from .analytics import department_scores, patterns
from .digests import send_daily_manager_summaries, send_weekly_founder_digest
from .models import Mistake, MistakeSettings, MistakeStatus
from .tests import MistakeBase


class AiSuggestTests(MistakeBase):
    def test_rules_never_blame_when_sop_inadequate(self):
        mid = self.log_mistake(self.manager, self.rahul).data["id"]
        m = Mistake.objects.get(pk=mid)
        m.sop_adequate = False
        m.save()
        s = suggest(m)
        self.assertEqual(s["classification"], "process")
        self.assertEqual(s["provider"], "rules")
        self.assertTrue(s["preventive_action"])

    def test_root_cause_mapping_and_endpoint_permission(self):
        mid = self.log_mistake(self.manager, self.rahul).data["id"]
        Mistake.objects.filter(pk=mid).update(root_cause="system_issue", occurrence_level=2)
        self.as_(self.manager)
        res = self.client.post(f"/api/mistakes/{mid}/ai_suggest/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["classification"], "system")
        self.assertIn("Repeat error", res.data["preventive_action"])
        self.as_(self.rahul)     # the employee can't ask for the reviewer's hints
        self.assertEqual(self.client.post(f"/api/mistakes/{mid}/ai_suggest/").status_code, 403)


class PatternTests(MistakeBase):
    def test_three_people_same_category_flags_the_process(self):
        for emp in (self.rahul, self.amit, self.vikram):
            self.log_mistake(self.admin, emp, category="Wrong Quantity")
        self.log_mistake(self.admin, self.rahul, category="Wrong Address")
        p = patterns(30)
        wq = next(c for c in p["categories"] if c["category"] == "Wrong Quantity")
        self.assertTrue(wq["process_suspect"])
        self.assertEqual(wq["distinct_employees"], 3)
        self.assertIn("question the PROCESS", wq["message"])
        wa = next(c for c in p["categories"] if c["category"] == "Wrong Address")
        self.assertFalse(wa["process_suspect"])

    def test_repeat_offenders_and_endpoint_scope(self):
        self.log_mistake(self.admin, self.rahul)
        self.log_mistake(self.admin, self.rahul)
        self.log_mistake(self.admin, self.vikram)        # purchase — outside meera's scope
        self.as_(self.manager)
        res = self.client.get("/api/mistakes/patterns/?days=30").data
        self.assertEqual(res["repeat_offenders"][0]["user"], self.rahul.id)
        total = sum(c["count"] for c in res["categories"])
        self.assertEqual(total, 2)                        # vikram's not counted
        self.as_(self.rahul)
        self.assertEqual(self.client.get("/api/mistakes/patterns/").status_code, 403)


class FounderViewTests(MistakeBase):
    def test_summary_counts_and_admin_only(self):
        self.log_mistake(self.admin, self.rahul, severity="critical", financial_loss="25000")
        mid = self.log_mistake(self.admin, self.amit).data["id"]
        Mistake.objects.filter(pk=mid).update(sla_due_at=timezone.now() - timedelta(hours=2))
        self.as_(self.admin)
        s = self.client.get("/api/mistakes/founder_summary/").data
        self.assertEqual(s["critical_open"], 1)
        self.assertEqual(s["sla_missed"], 1)
        self.assertEqual(s["loss_this_month"], 25000.0)
        self.as_(self.manager)
        self.assertEqual(self.client.get("/api/mistakes/founder_summary/").status_code, 403)


class DigestTests(MistakeBase):
    def test_daily_manager_summary_once_per_day(self):
        self.log_mistake(self.admin, self.rahul)           # manager = meera
        self.assertEqual(send_daily_manager_summaries(force=True), 1)
        self.assertTrue(Notification.objects.filter(
            user=self.manager, type="mistake_digest").exists())
        # guard: same day, not forced -> nothing
        self.assertEqual(send_daily_manager_summaries(), 0)
        self.assertEqual(MistakeSettings.get().last_daily_digest,
                         timezone.localtime().date())

    def test_weekly_founder_digest_mentions_patterns(self):
        for emp in (self.rahul, self.amit, self.vikram):
            self.log_mistake(self.admin, emp, category="Wrong Invoice")
        self.assertGreaterEqual(send_weekly_founder_digest(force=True), 1)
        n = Notification.objects.filter(user=self.admin, type="mistake_digest").latest("id")
        self.assertIn("Wrong Invoice", n.body)
        self.assertIn("3 people", n.body)
        self.assertEqual(send_weekly_founder_digest(), 0)   # guarded


class ScoringTests(MistakeBase):
    def test_employee_score_drops_by_mistake_penalty(self):
        now = timezone.now()
        Task.objects.create(title="T", assigned_to=self.rahul, created_by=self.manager,
                            effort_minutes=60, due_at=now + timedelta(hours=1),
                            status=TaskStatus.DONE, completed_at=now)   # task score 100
        self.log_mistake(self.manager, self.rahul, severity="high")     # penalty 6
        self.as_(self.manager)
        row = next(r for r in self.client.get(
            "/api/tasks/employees_report/?range=this_month").data["rows"]
            if r["user"] == self.rahul.id)
        self.assertEqual(row["task_score"], 100.0)
        self.assertEqual(row["mistake_penalty"], 6)
        self.assertEqual(row["score"], 94.0)
        self.assertEqual(row["mistakes"], 1)

    def test_department_score_components(self):
        mid = self.log_mistake(self.admin, self.rahul).data["id"]       # sales
        Mistake.objects.filter(pk=mid).update(occurrence_level=2, status=MistakeStatus.RESOLVED,
                                             resolved_at=timezone.now())  # within SLA
        today = timezone.localtime().date()
        d = department_scores(today.replace(day=1), today)
        sales = next(r for r in d["rows"] if r["department"] == "sales")
        self.assertEqual(sales["repeats"], 1)
        self.assertEqual(sales["sla_compliance"], 100.0)
        self.assertEqual(sales["breakdown"]["repeat_penalty"], 5)
        self.assertEqual(sales["score"], 95.0)
        self.assertIn("5/repeat", d["formula"])
        self.as_(self.manager)
        self.assertEqual(self.client.get("/api/mistakes/department_scores/").status_code, 200)
        self.as_(self.rahul)
        self.assertEqual(self.client.get("/api/mistakes/department_scores/").status_code, 403)
