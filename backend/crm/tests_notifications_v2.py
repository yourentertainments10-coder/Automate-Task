"""WhatsApp-automation groundwork: full-detail assignment ping (A),
completion fan-out to everyone involved (B), 2-hourly overdue re-pings and
the morning daily digest (C). Channels stay inert in tests — we assert the
notification rows that WhatsApp/Gmail will carry once credentials are live."""
from datetime import timedelta

from django.utils import timezone

from notifications.models import Notification

from .models import Task, TaskStatus
from .reminders import REMIND_EVERY_HOURS, send_daily_task_digest, send_task_reminders
from .tests_task_engine import Base


class AssignmentDetailTests(Base):
    def test_assignment_ping_carries_all_details(self):
        self.create_task(self.manager, self.rahul, title="Call Ravi",
                         description="revised quote", priority="high",
                         category="Calls", effort_minutes=45,
                         due_at=(timezone.now() + timedelta(days=1)).isoformat())
        n = Notification.objects.get(user=self.rahul, type="task_assigned")
        for piece in ("T-", "revised quote", "Effort: 45m", "Priority: High",
                      "Category: Calls", "Due:", "Assigned by: "):
            self.assertIn(piece, n.body)


class CompletionFanoutTests(Base):
    def test_completion_notifies_creator_and_followers_not_actor(self):
        res = self.create_task(self.manager, self.rahul, effort_minutes=30,
                               in_loop=[self.amit.id])
        task_id = res.data["id"]
        self.as_(self.rahul)
        self.client.post(f"/api/tasks/{task_id}/complete/",
                         {"remarks": "sab ho gaya", "actual_minutes": 40}, format="json")
        for user in (self.manager, self.amit):        # creator + in-loop
            n = Notification.objects.get(user=user, type="task_completed")
            self.assertIn("took 40m", n.body)
            self.assertIn("(assigned 30m)", n.body)
            self.assertIn("sab ho gaya", n.body)
        self.assertFalse(Notification.objects.filter(       # never the actor
            user=self.rahul, type="task_completed").exists())

    def test_admin_closing_someone_elses_task_notifies_the_assignee(self):
        task = Task.objects.create(title="X", assigned_to=self.rahul,
                                   created_by=self.manager)
        self.as_(self.admin)
        self.client.post(f"/api/tasks/{task.id}/complete/",
                         {"remarks": "closed by admin", "actual_minutes": 5},
                         format="json")
        self.assertTrue(Notification.objects.filter(
            user=self.rahul, type="task_completed").exists())


class OverdueRepingTests(Base):
    def test_overdue_repings_every_two_hours(self):
        task = Task.objects.create(title="Late", assigned_to=self.rahul,
                                   due_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(send_task_reminders(), 1)
        self.assertEqual(send_task_reminders(), 0)          # inside the window
        Task.objects.filter(pk=task.pk).update(
            reminded_at=timezone.now() - timedelta(hours=REMIND_EVERY_HOURS, minutes=1))
        self.assertEqual(send_task_reminders(), 1)          # 2h later -> again
        n = Notification.objects.filter(user=self.rahul, type="task_due").latest("id")
        self.assertIn("OVERDUE", n.body)


class DailyDigestTests(Base):
    def test_one_morning_digest_per_person(self):
        now = timezone.now()
        Task.objects.create(title="Overdue one", assigned_to=self.rahul,
                            due_at=now - timedelta(hours=3))
        Task.objects.create(title="Open no due", assigned_to=self.rahul)
        self.assertEqual(send_daily_task_digest(force=True), 1)
        self.assertEqual(send_daily_task_digest(force=True), 0)   # date guard
        n = Notification.objects.get(user=self.rahul, type="task_daily")
        self.assertIn("1 overdue", n.title)
        self.assertIn("2 open", n.title)
        self.assertIn("Overdue one", n.body)
