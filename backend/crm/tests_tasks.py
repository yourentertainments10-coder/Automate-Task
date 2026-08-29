from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from notifications.models import Notification

from .models import Lead, Task
from .reminders import send_task_reminders


def make(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


class TaskBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.manager = make("meera", Role.SALES_MANAGER, "sales")
        self.rahul = make("rahul", Role.SALES_EXECUTIVE, "sales")
        self.amit = make("amit", Role.SALES_EXECUTIVE, "sales")
        self.vikram = make("vikram", Role.PURCHASE, "purchase")
        self.lead = Lead.objects.create(customer_name="Ravi", department="sales",
                                        assigned_to=self.rahul)

    def as_(self, user):
        res = self.client.post("/api/auth/login", {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def titles(self, res):
        rows = res.data["results"] if "results" in res.data else res.data
        return sorted(t["title"] for t in rows)


class TaskApiTests(TaskBase):
    def test_manager_assigns_task_with_notification_and_lead_event(self):
        self.as_(self.manager)
        res = self.client.post("/api/tasks/", {
            "title": "Call Ravi with quote", "assigned_to": self.rahul.id,
            "effort_minutes": 45,
            "lead": self.lead.id, "priority": "high",
            "due_at": (timezone.now() + timedelta(days=1)).isoformat(),
        })
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["lead_name"], "Ravi")
        n = Notification.objects.get(user=self.rahul, type="task_assigned")
        self.assertIn("Call Ravi", n.title)
        self.assertTrue(self.lead.events.filter(body__contains="Task created").exists())

    def test_exec_assigns_to_peer_but_not_upward(self):
        # Task Engine v2 hierarchy: employee -> fellow employee is ALLOWED,
        # employee -> manager is not.
        self.as_(self.rahul)
        res = self.client.post("/api/tasks/", {"due_at": (timezone.now() + timedelta(days=1)).isoformat(), "title": "X", "assigned_to": self.amit.id,
                                               "effort_minutes": 30})
        self.assertEqual(res.status_code, 201)
        res = self.client.post("/api/tasks/", {"due_at": (timezone.now() + timedelta(days=1)).isoformat(), "title": "X", "assigned_to": self.manager.id,
                                               "effort_minutes": 30})
        self.assertEqual(res.status_code, 403)

    def test_exec_can_create_own_task(self):
        self.as_(self.rahul)
        res = self.client.post("/api/tasks/", {"due_at": (timezone.now() + timedelta(days=1)).isoformat(), "title": "Prepare catalogue", "assigned_to": self.rahul.id,
                                               "effort_minutes": 60})
        self.assertEqual(res.status_code, 201)
        # No self-notification
        self.assertFalse(Notification.objects.filter(user=self.rahul, type="task_assigned").exists())

    def test_cannot_link_invisible_lead(self):
        other_lead = Lead.objects.create(customer_name="P", department="purchase")
        self.as_(self.rahul)
        res = self.client.post("/api/tasks/", {"due_at": (timezone.now() + timedelta(days=1)).isoformat(), "title": "X", "assigned_to": self.rahul.id,
                                               "effort_minutes": 30, "lead": other_lead.id})
        self.assertEqual(res.status_code, 403)

    def test_scoping(self):
        Task.objects.create(title="T-rahul", assigned_to=self.rahul, created_by=self.manager)
        Task.objects.create(title="T-amit", assigned_to=self.amit, created_by=self.manager)
        Task.objects.create(title="T-vikram", assigned_to=self.vikram, created_by=self.admin)
        self.as_(self.admin)
        self.assertEqual(self.titles(self.client.get("/api/tasks/")), ["T-amit", "T-rahul", "T-vikram"])
        self.as_(self.manager)
        self.assertEqual(self.titles(self.client.get("/api/tasks/")), ["T-amit", "T-rahul"])
        self.as_(self.rahul)
        self.assertEqual(self.titles(self.client.get("/api/tasks/")), ["T-rahul"])
        self.as_(self.vikram)
        self.assertEqual(self.titles(self.client.get("/api/tasks/")), ["T-vikram"])

    def test_assignee_completes_task_sets_timestamp_and_lead_event(self):
        t = Task.objects.create(title="Call", assigned_to=self.rahul, created_by=self.manager,
                                lead=self.lead)
        self.as_(self.rahul)
        res = self.client.post(f"/api/tasks/{t.id}/complete/",
                               {"remarks": "called him", "actual_minutes": 15}, format="json")
        self.assertEqual(res.status_code, 200)
        t.refresh_from_db()
        self.assertIsNotNone(t.completed_at)
        self.assertTrue(self.lead.events.filter(body__contains="Task completed").exists())
        # reopening clears the timestamp
        self.client.patch(f"/api/tasks/{t.id}/", {"status": "open"})
        t.refresh_from_db()
        self.assertIsNone(t.completed_at)

    def test_other_exec_cannot_touch_foreign_task(self):
        t = Task.objects.create(title="Call", assigned_to=self.rahul, created_by=self.manager)
        self.as_(self.amit)
        self.assertEqual(self.client.patch(f"/api/tasks/{t.id}/", {"status": "done"}).status_code, 404)

    def test_direct_reassignment_is_admin_only_now(self):
        # B1 lockdown: neither the assignee nor even the creator can reassign
        # directly any more -- that goes through a Modification Request.
        # Admin can, and the new assignee is notified.
        t = Task.objects.create(title="Call", assigned_to=self.rahul, created_by=self.manager)
        self.as_(self.rahul)
        self.assertEqual(self.client.patch(f"/api/tasks/{t.id}/", {"assigned_to": self.amit.id}).status_code, 403)
        self.as_(self.manager)
        self.assertEqual(self.client.patch(f"/api/tasks/{t.id}/", {"assigned_to": self.amit.id}).status_code, 403)
        self.as_(self.admin)
        self.assertEqual(self.client.patch(f"/api/tasks/{t.id}/", {"assigned_to": self.amit.id}).status_code, 200)
        self.assertTrue(Notification.objects.filter(user=self.amit, type="task_assigned").exists())

    def test_overdue_filter(self):
        Task.objects.create(title="Late", assigned_to=self.rahul,
                            due_at=timezone.now() - timedelta(hours=1))
        Task.objects.create(title="Future", assigned_to=self.rahul,
                            due_at=timezone.now() + timedelta(days=1))
        self.as_(self.rahul)
        self.assertEqual(self.titles(self.client.get("/api/tasks/?overdue=true")), ["Late"])

    def test_dashboard_tile_counts_open_tasks(self):
        Task.objects.create(title="A", assigned_to=self.rahul)
        Task.objects.create(title="B", assigned_to=self.rahul, status="done")
        Task.objects.create(title="C", assigned_to=self.rahul,
                            due_at=timezone.now() - timedelta(hours=2))
        self.as_(self.admin)
        tiles = self.client.get("/api/dashboard/").data["tiles"]
        self.assertEqual(tiles["open_tasks"], 2)
        self.assertEqual(tiles["overdue_tasks"], 1)
        emp = next(e for e in self.client.get("/api/dashboard/").data["employees"]
                   if e["name"] == "rahul")
        self.assertEqual(emp["open_tasks"], 2)


class TaskReminderTests(TaskBase):
    def test_due_task_reminds_once_and_done_tasks_skip(self):
        t = Task.objects.create(title="Late", assigned_to=self.rahul,
                                due_at=timezone.now() - timedelta(hours=1))
        Task.objects.create(title="Done late", assigned_to=self.rahul, status="done",
                            due_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(send_task_reminders(), 1)
        self.assertEqual(send_task_reminders(), 0)
        n = Notification.objects.get(user=self.rahul, type="task_due")
        self.assertIn("Late", n.title)
