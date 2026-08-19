"""Reviewer's changes (19 Aug demo): managed categories with department-first
filtering (B5), mandatory effort (B6), In-Loop at creation (B7), escalate on
modification requests (B9), attachment retention (B11), reporting-manager
visibility (B12).
"""
import os
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from notifications.models import Notification

from .models import Task, TaskAttachment, TaskCategory, TaskChangeRequest, TaskStatus
from .reminders import purge_expired_attachments
from .tests_task_engine import MEDIA_TMP, Base


class CategoryTests(Base):
    """B5: dropdown from a managed list; employees pick, managers add."""

    def test_employee_unknown_category_rejected(self):
        res = self.create_task(self.rahul, self.rahul, category="Something Random")
        self.assertEqual(res.status_code, 400)
        self.assertIn("category", res.data)

    def test_employee_picks_seeded_category_case_insensitive(self):
        res = self.create_task(self.rahul, self.rahul, category="calls")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["category"], "Calls")   # canonical casing

    def test_department_category_needs_matching_department(self):
        # "Onboarding" is seeded for hr only
        res = self.create_task(self.rahul, self.rahul, category="Onboarding")
        self.assertEqual(res.status_code, 400)
        res = self.create_task(self.rahul, self.rahul,
                               category="Onboarding", department="hr")
        self.assertEqual(res.status_code, 201)

    def test_manager_typing_new_name_creates_category(self):
        res = self.create_task(self.manager, self.rahul,
                               category="Zebra Audit", department="sales")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(TaskCategory.objects.filter(
            name="Zebra Audit", department="sales", active=True).exists())

    def test_list_endpoint_filters_by_department(self):
        self.as_(self.rahul)
        names = {c["name"] for c in
                 self.client.get("/api/task-categories/?department=sales").data}
        self.assertIn("Calls", names)     # global
        self.assertIn("Quotes", names)    # sales
        self.assertNotIn("Onboarding", names)  # hr only

    def test_only_managers_write_categories(self):
        self.as_(self.rahul)
        self.assertEqual(self.client.post(
            "/api/task-categories/", {"name": "Nope"}).status_code, 403)
        self.as_(self.manager)
        res = self.client.post("/api/task-categories/",
                               {"name": "Test Drives", "department": "sales"})
        self.assertEqual(res.status_code, 201)
        # duplicate (case-insensitive) rejected
        self.assertEqual(self.client.post(
            "/api/task-categories/",
            {"name": "test drives", "department": "sales"}).status_code, 400)

    def test_delete_deactivates_instead_of_removing(self):
        cat = TaskCategory.objects.get(name="Quotes", department="sales")
        self.as_(self.manager)
        res = self.client.delete(f"/api/task-categories/{cat.id}/")
        self.assertEqual(res.status_code, 204)
        cat.refresh_from_db()
        self.assertFalse(cat.active)      # history intact, hidden from dropdown
        # re-adding the same name reactivates instead of duplicating
        res = self.client.post("/api/task-categories/",
                               {"name": "quotes", "department": "sales"})
        self.assertEqual(res.status_code, 201)
        cat.refresh_from_db()
        self.assertTrue(cat.active)
        self.assertEqual(TaskCategory.objects.filter(
            name__iexact="quotes", department="sales").count(), 1)


class MandatoryEffortTests(Base):
    """B6: no task without an effort value (API-created only)."""

    def test_create_without_effort_rejected(self):
        res = self.create_task(self.manager, self.rahul, effort_minutes=None)
        self.assertEqual(res.status_code, 400)
        self.assertIn("effort_minutes", res.data)

    def test_system_created_tasks_exempt(self):
        task = Task.objects.create(title="Webform import", assigned_to=self.rahul,
                                   created_by=self.admin)
        self.assertIsNone(task.effort_minutes)   # no exception raised


class InLoopTests(Base):
    """B7: colleagues named at creation follow the task from second one."""

    def test_in_loop_subscribes_and_notifies(self):
        res = self.create_task(self.manager, self.rahul,
                               in_loop=[self.amit.id, self.vikram.id])
        self.assertEqual(res.status_code, 201)
        task = Task.objects.get(pk=res.data["id"])
        self.assertTrue(task.subscribers.filter(pk=self.amit.pk).exists())
        self.assertTrue(task.subscribers.filter(pk=self.vikram.pk).exists())
        self.assertTrue(Notification.objects.filter(
            user=self.amit, type="task_inloop").exists())
        # in-loop members now see the task
        self.as_(self.vikram)
        ids = [t["id"] for t in self.client.get("/api/tasks/").data["results"]]
        self.assertIn(task.id, ids)

    def test_creator_not_double_added_via_in_loop(self):
        res = self.create_task(self.manager, self.rahul,
                               in_loop=[self.manager.id])
        task = Task.objects.get(pk=res.data["id"])
        self.assertFalse(Notification.objects.filter(
            user=self.manager, type="task_inloop").exists())
        self.assertEqual(task.subscribers.filter(pk=self.manager.pk).count(), 1)


class EscalateTests(Base):
    """B9: the creator can push a request up to admin instead of deciding."""

    def _request(self):
        res = self.create_task(self.manager, self.rahul)
        self.as_(self.rahul)
        self.client.post(f"/api/tasks/{res.data['id']}/request_change/",
                         {"changes": {"priority": "high"}, "reason": "urgent"},
                         format="json")
        return TaskChangeRequest.objects.latest("id")

    def test_creator_escalates_to_admin(self):
        req = self._request()
        self.as_(self.manager)
        res = self.client.post(f"/api/task-change-requests/{req.id}/review/",
                               {"decision": "escalated", "remarks": "your call"},
                               format="json")
        self.assertEqual(res.status_code, 200)
        req.refresh_from_db()
        self.assertTrue(req.escalated)
        self.assertEqual(req.status, "pending")          # not decided yet
        self.assertTrue(Notification.objects.filter(
            user=self.admin, type="task_change_request",
            title__startswith="ESCALATED").exists())
        # gone from the creator's inbox...
        inbox = self.client.get("/api/task-change-requests/?scope=inbox").data
        rows = inbox["results"] if "results" in inbox else inbox
        self.assertNotIn(req.id, [r["id"] for r in rows])
        # ...and the creator can no longer decide it
        self.assertEqual(self.client.post(
            f"/api/task-change-requests/{req.id}/review/",
            {"decision": "approved"}, format="json").status_code, 403)

    def test_admin_decides_escalated_request(self):
        req = self._request()
        self.as_(self.manager)
        self.client.post(f"/api/task-change-requests/{req.id}/review/",
                         {"decision": "escalated"}, format="json")
        self.as_(self.admin)
        res = self.client.post(f"/api/task-change-requests/{req.id}/review/",
                               {"decision": "approved"}, format="json")
        self.assertEqual(res.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, "approved")
        req.task.refresh_from_db()
        self.assertEqual(req.task.priority, "high")

    def test_admin_cannot_escalate(self):
        req = self._request()
        self.as_(self.admin)
        res = self.client.post(f"/api/task-change-requests/{req.id}/review/",
                               {"decision": "escalated"}, format="json")
        self.assertEqual(res.status_code, 400)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class AttachmentRetentionTests(Base):
    """B11: files auto-delete 7 days after the task is completed."""

    def _attach(self, task):
        return TaskAttachment.objects.create(
            task=task, filename="proof.txt",
            file=SimpleUploadedFile("proof.txt", b"evidence"),
            uploaded_by=self.rahul)

    def _done_task(self, days_ago):
        task = Task.objects.create(title="Old", assigned_to=self.rahul,
                                   created_by=self.manager,
                                   status=TaskStatus.DONE,
                                   completed_at=timezone.now() - timedelta(days=days_ago))
        return task

    def test_purges_only_expired_done_tasks(self):
        old = self._attach(self._done_task(8))
        fresh = self._attach(self._done_task(2))
        open_task = Task.objects.create(title="Open", assigned_to=self.rahul,
                                        created_by=self.manager)
        kept_open = self._attach(open_task)

        removed = purge_expired_attachments()
        self.assertEqual(removed, 1)
        remaining = set(TaskAttachment.objects.values_list("id", flat=True))
        self.assertNotIn(old.id, remaining)
        self.assertIn(fresh.id, remaining)
        self.assertIn(kept_open.id, remaining)

    def test_zero_retention_disables_purge(self):
        self._attach(self._done_task(30))
        with mock.patch.dict(os.environ, {"TASK_ATTACHMENT_RETENTION_DAYS": "0"}):
            self.assertEqual(purge_expired_attachments(), 0)
        self.assertEqual(TaskAttachment.objects.count(), 1)


class ReportingManagerVisibilityTests(Base):
    """B12: your reporting manager sees your tasks, whoever assigned them."""

    def test_reporting_manager_sees_reportee_tasks_cross_department(self):
        # vikram (purchase) reports to meera (sales manager)
        self.vikram.reporting_manager = self.manager
        self.vikram.save(update_fields=["reporting_manager"])
        task = Task.objects.create(title="Stock check", assigned_to=self.vikram,
                                   created_by=self.admin)
        self.as_(self.manager)
        ids = [t["id"] for t in self.client.get("/api/tasks/").data["results"]]
        self.assertIn(task.id, ids)

    def test_non_manager_colleague_does_not_gain_visibility(self):
        task = Task.objects.create(title="Private", assigned_to=self.vikram,
                                   created_by=self.admin)
        self.as_(self.rahul)   # no reporting link, not sales-dept assignee
        ids = [t["id"] for t in self.client.get("/api/tasks/").data["results"]]
        self.assertNotIn(task.id, ids)
