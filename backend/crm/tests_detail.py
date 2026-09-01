"""Phase E: task detail (checklist, sub-tasks, comments, per-task feed) and
the AI layer's deterministic fallback."""
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
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
        # a bare tick is refused — every step has to say what was done
        self.assertEqual(self.client.post(
            f"/api/tasks/{self.task.id}/check/{item.id}/").status_code, 400)
        res = self.client.post(f"/api/tasks/{self.task.id}/check/{item.id}/",
                               {"note": "collected them"}, format="json")
        self.assertTrue(next(i for i in res.data if i["id"] == item.id)["done"])
        # completion is logged to the feed
        self.assertTrue(self.task.activities.filter(
            text__startswith="Step done:").exists())
        # a finished step stays: only an open one can be removed
        self.assertEqual(self.client.post(
            f"/api/tasks/{self.task.id}/check/{item.id}/?delete=true").status_code, 400)
        other = self.task.checklist.filter(done=False).first()
        res = self.client.post(f"/api/tasks/{self.task.id}/check/{other.id}/?delete=true")
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


class AssignerChecklistTests(Base):
    """The person GIVING the task breaks it into steps; the assignee ticks
    each one with a note and cannot finish until every step is done."""

    def make_task_with_steps(self, steps=("Collect invoice", "Verify amount")):
        res = self.create_task(self.manager, self.rahul, title="Month close",
                               checklist=list(steps))
        self.assertEqual(res.status_code, 201, res.data)
        return res.data["id"]

    def test_assigner_sets_the_steps_at_creation(self):
        tid = self.make_task_with_steps()
        self.as_(self.rahul)
        steps = self.client.get(f"/api/tasks/{tid}/").data["checklist"]
        self.assertEqual([s["text"] for s in steps], ["Collect invoice", "Verify amount"])
        self.assertTrue(all(s["done"] is False for s in steps))

    def test_ticking_a_step_requires_a_note(self):
        tid = self.make_task_with_steps()
        self.as_(self.rahul)
        sid = self.client.get(f"/api/tasks/{tid}/").data["checklist"][0]["id"]
        res = self.client.post(f"/api/tasks/{tid}/check/{sid}/", {}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("note", res.data)

        res = self.client.post(f"/api/tasks/{tid}/check/{sid}/",
                               {"note": "Picked it up from accounts"}, format="json")
        self.assertEqual(res.status_code, 200)
        step = next(s for s in res.data if s["id"] == sid)
        self.assertTrue(step["done"])
        self.assertEqual(step["note"], "Picked it up from accounts")
        self.assertEqual(step["done_by_name"], self.rahul.get_full_name() or self.rahul.username)

    def test_cannot_complete_while_a_step_is_open(self):
        tid = self.make_task_with_steps()
        self.as_(self.rahul)
        res = self.client.post(f"/api/tasks/{tid}/complete/",
                               {"remarks": "all done", "actual_minutes": 30}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data.get("needs"), "checklist")

        # tick both, then it goes through
        for s in self.client.get(f"/api/tasks/{tid}/").data["checklist"]:
            self.client.post(f"/api/tasks/{tid}/check/{s['id']}/",
                             {"note": "done properly"}, format="json")
        res = self.client.post(f"/api/tasks/{tid}/complete/",
                               {"remarks": "all done", "actual_minutes": 30}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Task.objects.get(pk=tid).status, "done")

    def test_the_status_dropdown_cannot_skip_the_checklist_either(self):
        tid = self.make_task_with_steps()
        self.as_(self.rahul)
        res = self.client.patch(f"/api/tasks/{tid}/", {"status": "done"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertNotEqual(Task.objects.get(pk=tid).status, "done")

    def test_a_done_step_cannot_be_deleted_and_reopening_clears_the_note(self):
        tid = self.make_task_with_steps()
        self.as_(self.rahul)
        sid = self.client.get(f"/api/tasks/{tid}/").data["checklist"][0]["id"]
        self.client.post(f"/api/tasks/{tid}/check/{sid}/", {"note": "finished it"}, format="json")
        self.assertEqual(self.client.post(
            f"/api/tasks/{tid}/check/{sid}/?delete=true").status_code, 400)
        res = self.client.post(f"/api/tasks/{tid}/check/{sid}/", {}, format="json")
        step = next(s for s in res.data if s["id"] == sid)
        self.assertFalse(step["done"])
        self.assertEqual(step["note"], "")

    def test_a_task_without_steps_completes_as_before(self):
        res = self.create_task(self.manager, self.rahul, title="Simple")
        tid = res.data["id"]
        self.as_(self.rahul)
        res = self.client.post(f"/api/tasks/{tid}/complete/",
                               {"remarks": "nothing to it", "actual_minutes": 5}, format="json")
        self.assertEqual(res.status_code, 200, res.data)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TaskAttachmentTests(Base):
    """The assigner can hand over an invoice/photo with the task, so the
    assignee has what they need to actually do it."""

    def make_task(self):
        return self.create_task(self.manager, self.rahul, title="Pay vendor").data["id"]

    def png(self, name="invoice.png"):
        return SimpleUploadedFile(name, b"\x89PNG\r\n\x1a\nfake", content_type="image/png")

    def test_assigner_attaches_a_file_and_assignee_sees_it(self):
        tid = self.make_task()
        self.as_(self.manager)
        res = self.client.post(f"/api/tasks/{tid}/upload/", {"file": self.png()})
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual([f["filename"] for f in res.data], ["invoice.png"])

        self.as_(self.rahul)
        files = self.client.get(f"/api/tasks/{tid}/files/").data
        self.assertEqual(files[0]["filename"], "invoice.png")
        self.assertTrue(files[0]["url"])

    def test_attaching_is_logged_so_everyone_can_see_it_arrived(self):
        tid = self.make_task()
        self.as_(self.manager)
        self.client.post(f"/api/tasks/{tid}/upload/", {"file": self.png("po.png")})
        self.assertTrue(Task.objects.get(pk=tid).activities
                        .filter(text__startswith="Attached: po.png").exists())

    def test_several_files_at_once(self):
        tid = self.make_task()
        self.as_(self.manager)
        res = self.client.post(f"/api/tasks/{tid}/upload/",
                               {"file": [self.png("a.png"), self.png("b.png")]})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(res.data), 2)

    def test_an_outsider_cannot_attach(self):
        tid = self.make_task()
        self.as_(self.amit)          # neither assignee nor creator
        res = self.client.post(f"/api/tasks/{tid}/upload/", {"file": self.png()})
        self.assertIn(res.status_code, (403, 404))

    def test_no_file_is_a_clear_error(self):
        tid = self.make_task()
        self.as_(self.manager)
        res = self.client.post(f"/api/tasks/{tid}/upload/", {})
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.data)

    def test_oversized_file_is_refused(self):
        tid = self.make_task()
        self.as_(self.manager)
        big = SimpleUploadedFile("big.bin", b"x" * (10 * 1024 * 1024 + 1))
        res = self.client.post(f"/api/tasks/{tid}/upload/", {"file": big})
        self.assertEqual(res.status_code, 400)
        self.assertIn("10 MB", str(res.data))


class StorageConfigTests(TestCase):
    """Uploads must switch to S3 when a bucket is configured and keep working
    on the local disk when it is not."""

    def test_local_disk_by_default(self):
        from django.conf import settings
        self.assertFalse(settings.USE_S3)
        self.assertIn("FileSystemStorage", settings.STORAGES["default"]["BACKEND"])

    def test_s3_backend_is_selected_when_a_bucket_is_set(self):
        """Reload settings with a bucket present and confirm the S3 backend
        is chosen — without ever contacting AWS."""
        import importlib
        from unittest import mock
        with mock.patch.dict("os.environ", {
                "AWS_STORAGE_BUCKET_NAME": "test-bucket",
                "AWS_ACCESS_KEY_ID": "AKIATEST",
                "AWS_SECRET_ACCESS_KEY": "secret",
                "AWS_S3_REGION_NAME": "ap-south-1"}):
            import config.settings as s
            src = importlib.util.spec_from_file_location("probe", s.__file__)
            probe = importlib.util.module_from_spec(src)
            probe.__dict__["__name__"] = "probe"
            import sys as _sys
            argv = _sys.argv
            _sys.argv = ["manage.py", "runserver"]     # not "test": S3 stays on
            try:
                src.loader.exec_module(probe)
            finally:
                _sys.argv = argv
        self.assertTrue(probe.USE_S3)
        self.assertEqual(probe.STORAGES["default"]["BACKEND"],
                         "storages.backends.s3.S3Storage")
        self.assertFalse(probe.AWS_S3_FILE_OVERWRITE)   # never clobber a file
        self.assertTrue(probe.AWS_QUERYSTRING_AUTH)     # links are signed

    def test_the_s3_backend_actually_imports(self):
        from storages.backends.s3 import S3Storage
        self.assertTrue(callable(S3Storage))
