"""Phase E: task detail (checklist, sub-tasks, comments, per-task feed) and
the AI layer's deterministic fallback."""
from datetime import timedelta

from django.utils import timezone

from .ai_tasks import draft_task, review_sentence
from .models import Task, TaskChecklistItem
from .tests_task_engine import Base

from django.test import TestCase


class ChecklistTests(Base):
    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(title="Big job", assigned_to=self.rahul,
                                        created_by=self.manager)

    def test_add_toggle_delete_checklist(self):
        self.as_(self.rahul)
        res = self.client.post(f"/api/tasks/{self.task.id}/add_check/",
                               {"text": "Collect part numbers"}, format="json")
        self.assertEqual(res.status_code, 201)
        self.client.post(f"/api/tasks/{self.task.id}/add_check/",
                         {"text": "Verify prices"}, format="json")
        item = self.task.checklist.first()
        res = self.client.post(f"/api/tasks/{self.task.id}/check/{item.id}/")
        self.assertTrue(next(i for i in res.data if i["id"] == item.id)["done"])
        # completion is logged to the feed
        self.assertTrue(self.task.activities.filter(
            text__startswith="Checklist ✓").exists())
        res = self.client.post(f"/api/tasks/{self.task.id}/check/{item.id}/?delete=true")
        self.assertEqual(len(res.data), 1)

    def test_outsider_cannot_edit_checklist(self):
        self.as_(self.amit)
        res = self.client.post(f"/api/tasks/{self.task.id}/add_check/",
                               {"text": "sneaky"}, format="json")
        self.assertIn(res.status_code, (403, 404))

    def test_detail_includes_checklist_and_subtasks(self):
        TaskChecklistItem.objects.create(task=self.task, text="step 1")
        Task.objects.create(title="Child", assigned_to=self.rahul,
                            created_by=self.manager, parent=self.task)
        self.as_(self.rahul)
        res = self.client.get(f"/api/tasks/{self.task.id}/").data
        self.assertEqual(res["checklist"][0]["text"], "step 1")
        self.assertEqual(res["subtasks"][0]["title"], "Child")


class SubtaskTests(Base):
    def test_subtask_created_via_api_one_level_only(self):
        parent = Task.objects.create(title="Parent", assigned_to=self.rahul,
                                     created_by=self.manager)
        self.as_(self.manager)
        res = self.client.post("/api/tasks/", {
            "due_at": (timezone.now() + timedelta(days=1)).isoformat(),
            "title": "Child", "assigned_to": self.rahul.id,
            "effort_minutes": 15, "parent": parent.id}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["parent_code"], parent.code)
        # grandchild refused
        res = self.client.post("/api/tasks/", {
            "due_at": (timezone.now() + timedelta(days=1)).isoformat(),
            "title": "Grandchild", "assigned_to": self.rahul.id,
            "effort_minutes": 15, "parent": res.data["id"]}, format="json")
        self.assertEqual(res.status_code, 400)


class CommentTests(Base):
    def test_comment_logs_and_notifies(self):
        from notifications.models import Notification
        task = Task.objects.create(title="T", assigned_to=self.rahul,
                                   created_by=self.manager)
        self.as_(self.manager)
        res = self.client.post(f"/api/tasks/{task.id}/comment/",
                               {"text": "Ravi ko pehle call karna"}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data[0]["kind"], "comment")
        self.assertTrue(Notification.objects.filter(
            user=self.rahul, type="task_comment").exists())
        # per-task feed returns it
        feed = self.client.get(f"/api/tasks/{task.id}/activity/").data
        self.assertTrue(any(a["kind"] == "comment" for a in feed))


class AiFallbackTests(TestCase):
    """AI_ENABLED is off in tests — the deterministic layer must still work."""

    def test_draft_rules_fallback(self):
        d = draft_task("Call Ravi about the brake pads, then send the quotation, "
                       "then follow up tomorrow")
        self.assertEqual(d["provider"], "rules")
        self.assertTrue(d["title"].startswith("Call ravi") or "Call" in d["title"])
        self.assertGreaterEqual(len(d["checklist"]), 1)

    def test_review_sentences_match_sirs_categories(self):
        base = {"completed": 10, "total": 12, "overdue": 0, "multitask_days": 0,
                "on_time_rate": 95.0, "score": 90.0}
        self.assertIn("Next level", review_sentence(base))
        self.assertIn("Multitasker", review_sentence(
            {**base, "multitask_days": 5, "on_time_rate": 40.0, "score": 50.0}))
        self.assertIn("Slow", review_sentence(
            {**base, "on_time_rate": 30.0, "score": 40.0, "overdue": 8}))
        self.assertIn("No completions", review_sentence({**base, "completed": 0}))

    def test_ai_draft_endpoint(self):
        from rest_framework.test import APIClient
        from accounts.models import Role, User
        u = User.objects.create_user("drafter", "d@x.com", "pass@12345",
                                     role=Role.SALES_EXECUTIVE)
        c = APIClient()
        r = c.post("/api/auth/login", {"username": "drafter", "password": "pass@12345"})
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        res = c.post("/api/tasks/ai_draft/", {"prompt": "Audit the Hyundai parts shelf"},
                     format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["title"])
