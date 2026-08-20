"""Phase P: In-Progress status updates, mandatory completion description +
actual effort, and the Time Earned vs Time Spent report."""
from datetime import timedelta

from django.utils import timezone

from .models import Task, TaskActivity, TaskStatus
from .tests_task_engine import Base


class ProgressUpdateTests(Base):
    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(title="Big job", assigned_to=self.rahul,
                                        created_by=self.manager, effort_minutes=120)

    def test_update_sets_percent_effort_and_logs(self):
        self.as_(self.rahul)
        res = self.client.post(f"/api/tasks/{self.task.id}/progress/",
                               {"percent": 60, "spent_minutes": 45,
                                "comment": "waiting on vendor"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["progress_percent"], 60)
        self.assertEqual(res.data["actual_minutes"], 45)
        self.assertEqual(res.data["status"], "in_progress")   # open -> in_progress
        log = TaskActivity.objects.filter(task=self.task,
                                          text__startswith="Status update").first()
        self.assertIn("60% done", log.text)
        self.assertIn("45m spent", log.text)
        self.assertIn("waiting on vendor", log.text)

    def test_updates_are_repeatable(self):
        self.as_(self.rahul)
        self.client.post(f"/api/tasks/{self.task.id}/progress/",
                         {"percent": 30}, format="json")
        self.client.post(f"/api/tasks/{self.task.id}/progress/",
                         {"percent": 80, "spent_minutes": 100}, format="json")
        self.task.refresh_from_db()
        self.assertEqual(self.task.progress_percent, 80)
        self.assertEqual(self.task.actual_minutes, 100)
        self.assertEqual(TaskActivity.objects.filter(
            task=self.task, text__startswith="Status update").count(), 2)

    def test_creator_gets_notified(self):
        from notifications.models import Notification
        self.as_(self.rahul)
        self.client.post(f"/api/tasks/{self.task.id}/progress/",
                         {"percent": 50}, format="json")
        self.assertTrue(Notification.objects.filter(
            user=self.manager, type="task_progress").exists())

    def test_only_assignee_and_valid_values(self):
        self.as_(self.amit)   # not the assignee
        self.assertEqual(self.client.post(
            f"/api/tasks/{self.task.id}/progress/", {"percent": 10},
            format="json").status_code, 404)   # not even visible to him
        self.as_(self.rahul)
        self.assertEqual(self.client.post(
            f"/api/tasks/{self.task.id}/progress/", {"percent": 150},
            format="json").status_code, 400)
        self.assertEqual(self.client.post(
            f"/api/tasks/{self.task.id}/progress/", {}, format="json").status_code, 400)

    def test_no_updates_after_done(self):
        self.as_(self.rahul)
        self.client.post(f"/api/tasks/{self.task.id}/complete/",
                         {"remarks": "ok", "actual_minutes": 90}, format="json")
        res = self.client.post(f"/api/tasks/{self.task.id}/progress/",
                               {"percent": 10}, format="json")
        self.assertEqual(res.status_code, 400)


class TimeReportTests(Base):
    def _done(self, assignee, effort, actual):
        task = Task.objects.create(title="T", assigned_to=assignee,
                                   created_by=self.manager, effort_minutes=effort,
                                   status=TaskStatus.DONE, actual_minutes=actual,
                                   completed_at=timezone.now())
        return task

    def test_earned_vs_spent_math(self):
        self._done(self.rahul, 30, 60)
        self._done(self.rahul, 60, 45)
        self._done(self.rahul, None, 20)     # no effort value -> earns 0, visible
        self.as_(self.manager)
        rows = self.client.get("/api/tasks/time_report/?range=this_month").data["rows"]
        me = next(r for r in rows if r["user"] == self.rahul.id)
        self.assertEqual(me["done"], 3)
        self.assertEqual(me["time_earned_minutes"], 90)
        self.assertEqual(me["time_spent_minutes"], 125)
        self.assertEqual(me["no_effort_tasks"], 1)

    def test_employee_sees_only_self(self):
        self._done(self.rahul, 30, 30)
        self._done(self.amit, 30, 30)
        self.as_(self.rahul)
        rows = self.client.get("/api/tasks/time_report/").data["rows"]
        self.assertEqual([r["user"] for r in rows], [self.rahul.id])

    def test_manager_sees_department_admin_sees_all(self):
        self._done(self.rahul, 30, 30)       # sales
        self._done(self.vikram, 40, 40)      # purchase
        self.as_(self.manager)               # sales manager
        rows = self.client.get("/api/tasks/time_report/").data["rows"]
        self.assertIn(self.rahul.id, [r["user"] for r in rows])
        self.assertNotIn(self.vikram.id, [r["user"] for r in rows])
        self.as_(self.admin)
        rows = self.client.get("/api/tasks/time_report/").data["rows"]
        self.assertIn(self.vikram.id, [r["user"] for r in rows])

    def test_range_filters_out_old_completions(self):
        task = self._done(self.rahul, 30, 30)
        Task.objects.filter(pk=task.pk).update(
            completed_at=timezone.now() - timedelta(days=400))
        self.as_(self.admin)
        rows = self.client.get("/api/tasks/time_report/?range=this_year").data["rows"]
        self.assertEqual(rows, [])
        rows = self.client.get("/api/tasks/time_report/?range=all").data["rows"]
        self.assertEqual(len(rows), 1)
