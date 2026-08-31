"""Phase D: employees report (score/multitasker), daily grain, disputes."""
from datetime import timedelta

from django.utils import timezone

from .models import Task, TaskStatus
from .tests_task_engine import Base


def mk(assignee, creator, **kw):
    return Task.objects.create(title=kw.pop("title", "T"), assigned_to=assignee,
                               created_by=creator, **kw)


class EmployeesReportTests(Base):
    def test_counts_score_and_formula(self):
        now = timezone.now()
        # rahul: 2 completed (1 in time, 1 delayed), effort fully earned
        mk(self.rahul, self.manager, effort_minutes=60, due_at=now + timedelta(hours=1),
           status=TaskStatus.DONE, completed_at=now)                     # in time
        mk(self.rahul, self.manager, effort_minutes=30, due_at=now - timedelta(days=1),
           status=TaskStatus.DONE, completed_at=now)                     # delayed
        mk(self.rahul, self.manager, effort_minutes=30,
           due_at=now + timedelta(days=1))                               # open
        self.as_(self.manager)
        res = self.client.get("/api/tasks/employees_report/?range=all").data
        self.assertIn("Score = 60", res["formula"])
        row = next(r for r in res["rows"] if r["user"] == self.rahul.id)
        self.assertEqual(row["total"], 3)
        self.assertEqual(row["completed"], 2)
        self.assertEqual(row["in_time"], 1)
        self.assertEqual(row["delayed"], 1)
        self.assertEqual(row["pending"], 1)
        self.assertEqual(row["time_assigned_minutes"], 120)
        self.assertEqual(row["time_earned_minutes"], 90)
        # score = 60*(1/2) + 40*(90/120) = 30 + 30 = 60
        self.assertEqual(row["score"], 60.0)
        self.assertEqual(row["on_time_rate"], 50.0)
        self.assertEqual(row["effort_ratio"], 75.0)

    def test_employee_sees_only_self_manager_department(self):
        mk(self.rahul, self.manager, due_at=timezone.now())
        mk(self.vikram, self.admin, due_at=timezone.now())    # purchase
        self.as_(self.rahul)
        rows = self.client.get("/api/tasks/employees_report/").data["rows"]
        self.assertEqual([r["user"] for r in rows], [self.rahul.id])
        self.as_(self.manager)
        ids = [r["user"] for r in self.client.get("/api/tasks/employees_report/").data["rows"]]
        self.assertIn(self.rahul.id, ids)
        self.assertNotIn(self.vikram.id, ids)
        self.as_(self.admin)
        ids = [r["user"] for r in self.client.get("/api/tasks/employees_report/").data["rows"]]
        self.assertIn(self.vikram.id, ids)

    def test_multitask_days_counted(self):
        now = timezone.now()
        # 3 tasks all active today -> today is a multitask day
        for i in range(3):
            mk(self.rahul, self.manager, title=f"P{i}", due_at=now)
        self.as_(self.manager)
        row = next(r for r in self.client.get(
            "/api/tasks/employees_report/?range=today").data["rows"]
            if r["user"] == self.rahul.id)
        self.assertGreaterEqual(row["multitask_days"], 1)
        # amit with one task: no multitask day
        mk(self.amit, self.manager, due_at=now)
        row = next(r for r in self.client.get(
            "/api/tasks/employees_report/?range=today").data["rows"]
            if r["user"] == self.amit.id)
        self.assertEqual(row["multitask_days"], 0)

    def test_daily_grain_credits_completion_day(self):
        now = timezone.now()
        mk(self.rahul, self.manager, effort_minutes=45, actual_minutes=50,
           due_at=now, status=TaskStatus.DONE, completed_at=now)
        self.as_(self.manager)
        rows = self.client.get(
            "/api/tasks/employees_report/?range=this_week&grain=daily").data["rows"]
        today = timezone.localtime(now).date().isoformat()
        row = next(r for r in rows if str(r["date"]) == today)
        self.assertEqual(row["completed"], 1)
        self.assertEqual(row["time_earned_minutes"], 45)
        self.assertEqual(row["time_spent_minutes"], 50)

    def test_custom_range_validation(self):
        self.as_(self.manager)
        self.assertEqual(self.client.get(
            "/api/tasks/employees_report/?range=custom").status_code, 400)
        self.assertEqual(self.client.get(
            "/api/tasks/employees_report/?range=custom&start=2026-08-01&end=2026-07-01"
        ).status_code, 400)
        self.assertEqual(self.client.get(
            "/api/tasks/employees_report/?range=custom&start=2026-08-01&end=2026-08-20"
        ).status_code, 200)


class EffortDisputeTests(Base):
    def test_only_diverging_estimates_listed(self):
        now = timezone.now()
        agree = mk(self.rahul, self.manager, title="Agree", effort_minutes=60,
                   assignee_estimate_minutes=60, due_at=now)
        fight = mk(self.rahul, self.manager, title="Amit said 1h Bhavna said 4",
                   effort_minutes=60, assignee_estimate_minutes=240, due_at=now)
        mk(self.rahul, self.manager, title="No estimate", effort_minutes=60, due_at=now)
        self.as_(self.manager)
        rows = self.client.get("/api/tasks/effort_disputes/?range=this_week").data["rows"]
        self.assertEqual([r["id"] for r in rows], [fight.id])
        self.assertEqual(rows[0]["effort_minutes"], 60)
        self.assertEqual(rows[0]["estimate_minutes"], 240)

    def test_employee_scope_is_self(self):
        now = timezone.now()
        mk(self.amit, self.manager, effort_minutes=10,
           assignee_estimate_minutes=99, due_at=now)
        self.as_(self.rahul)
        self.assertEqual(self.client.get(
            "/api/tasks/effort_disputes/").data["rows"], [])
