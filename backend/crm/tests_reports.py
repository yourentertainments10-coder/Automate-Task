"""Phase D: employees report (score/multitasker), daily grain, disputes."""
from datetime import datetime, timedelta

from django.test import TestCase
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


class RangeBoundsTests(TestCase):
    """A week that starts 31 Aug and ends 6 Sep sits in two months, so a task
    can be in This Week and not in This Month. That is correct, and it looked
    like a bug until the dashboard started saying which dates it counted."""

    def bounds(self, name, when):
        from crm.task_views import _range_bounds
        return _range_bounds(name, when)

    def setUp(self):
        # Thursday 03 Sep 2026 — the day the question was actually asked
        self.now = timezone.make_aware(datetime(2026, 9, 3, 12, 0))

    def test_week_runs_monday_to_sunday(self):
        s, e = self.bounds("this_week", self.now)
        self.assertEqual((s.day, s.month), (31, 8))     # Monday
        self.assertEqual((e.day, e.month), (6, 9))      # Sunday
        self.assertEqual(s.weekday(), 0)
        self.assertEqual(e.weekday(), 6)

    def test_last_week_is_the_seven_days_before_that(self):
        s, e = self.bounds("last_week", self.now)
        self.assertEqual((s.day, s.month), (24, 8))
        self.assertEqual((e.day, e.month), (30, 8))

    def test_this_month_is_the_real_calendar_month(self):
        s, e = self.bounds("this_month", self.now)
        self.assertEqual((s.day, s.month), (1, 9))
        self.assertEqual((e.day, e.month), (30, 9))     # September has 30 days

    def test_last_month_ends_on_its_own_last_day(self):
        s, e = self.bounds("last_month", self.now)
        self.assertEqual((s.day, s.month), (1, 8))
        self.assertEqual((e.day, e.month), (31, 8))     # August has 31

    def test_month_end_does_not_bleed_into_the_next_month(self):
        """The bug this replaced: day=28 + 10 days landed in the month after."""
        for month, last in ((1, 31), (2, 28), (4, 30), (12, 31)):
            s, e = self.bounds("this_month", timezone.make_aware(datetime(2026, month, 15, 9, 0)))
            self.assertEqual((s.month, s.day), (month, 1))
            self.assertEqual((e.month, e.day), (month, last), f"month {month}")

    def test_february_in_a_leap_year(self):
        s, e = self.bounds("this_month", timezone.make_aware(datetime(2028, 2, 10, 9, 0)))
        self.assertEqual((e.month, e.day), (2, 29))

    def test_a_week_may_legitimately_straddle_two_months(self):
        ws, we = self.bounds("this_week", self.now)
        ms, me = self.bounds("this_month", self.now)
        self.assertLess(ws, ms)          # Monday 31 Aug is before 1 Sep
        self.assertTrue(ws <= ms <= we)  # ...and the month starts mid-week
