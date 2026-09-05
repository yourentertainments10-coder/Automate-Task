"""Task Engine v2, Phases A & B: assignment hierarchy, effort values,
soft delete, edit lockdown, modification requests, completion evidence.
"""
import tempfile
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from notifications.models import Notification

from .models import Task, TaskChangeRequest, TaskSettings, TaskStatus, TaskStatus

MEDIA_TMP = tempfile.mkdtemp()


def make(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


class Base(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.manager = make("meera", Role.SALES_MANAGER)
        self.hr = make("neha", Role.HR_MANAGER, "hr")
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)
        self.amit = make("amit", Role.SALES_EXECUTIVE)
        self.vikram = make("vikram", Role.PURCHASE, "purchase")
        TaskSettings.objects.all().delete()   # defaults: nothing mandatory

    def as_(self, user):
        res = self.client.post("/api/auth/login", {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def create_task(self, as_user, assignee, **extra):
        self.as_(as_user)
        # effort_minutes is mandatory at the API since B6 — every helper
        # call gets one unless the test overrides it
        body = {"title": "T", "assigned_to": assignee.id,
                "effort_minutes": 30,
                # due_at is mandatory too — no due date means no reminder,
                # no overdue flag and no on-time score
                "due_at": (timezone.now() + timedelta(days=1)).isoformat(),
                **extra}
        return self.client.post("/api/tasks/", body, format="json")


class HierarchyTests(Base):
    """A1: level-based — admin(3) > managers(2) > employees(1)."""

    def test_employee_can_assign_to_fellow_employee_cross_department(self):
        res = self.create_task(self.rahul, self.vikram)   # sales exec -> purchase
        self.assertEqual(res.status_code, 201)

    def test_employee_cannot_assign_upward(self):
        self.assertEqual(self.create_task(self.rahul, self.manager).status_code, 403)
        self.assertEqual(self.create_task(self.rahul, self.admin).status_code, 403)

    def test_manager_can_assign_to_manager_and_below_but_not_admin(self):
        self.assertEqual(self.create_task(self.manager, self.hr).status_code, 201)
        self.assertEqual(self.create_task(self.manager, self.rahul).status_code, 201)
        self.assertEqual(self.create_task(self.manager, self.admin).status_code, 403)

    def test_admin_assigns_to_anyone(self):
        self.assertEqual(self.create_task(self.admin, self.manager).status_code, 201)
        self.assertEqual(self.create_task(self.admin, self.rahul).status_code, 201)

    def test_assignees_endpoint_is_level_filtered(self):
        self.as_(self.rahul)
        names = {u["username"] for u in self.client.get("/api/tasks/assignees/").data}
        self.assertEqual(names, {"rahul", "amit", "vikram"})     # employees only
        self.as_(self.manager)
        names = {u["username"] for u in self.client.get("/api/tasks/assignees/").data}
        self.assertEqual(names, {"meera", "neha", "rahul", "amit", "vikram"})
        self.as_(self.admin)
        self.assertEqual(len(self.client.get("/api/tasks/assignees/").data), 6)

    def test_admin_reassignment_still_respects_targets(self):
        task = Task.objects.create(title="X", assigned_to=self.rahul, created_by=self.manager)
        self.as_(self.admin)
        res = self.client.patch(f"/api/tasks/{task.id}/", {"assigned_to": self.amit.id}, format="json")
        self.assertEqual(res.status_code, 200)


class EffortTests(Base):
    """A2: assigner's effort + assignee's one-time counter-estimate."""

    def test_assigner_sets_effort_on_creation(self):
        res = self.create_task(self.manager, self.rahul, effort_minutes=120)
        self.assertEqual(res.data["effort_minutes"], 120)

    def test_assignee_estimates_once_and_it_is_logged(self):
        task_id = self.create_task(self.manager, self.rahul, effort_minutes=60).data["id"]
        self.as_(self.rahul)
        res = self.client.post(f"/api/tasks/{task_id}/estimate/", {"minutes": 240}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["assignee_estimate_minutes"], 240)
        self.assertEqual(res.data["effort_minutes"], 60)          # never overwritten
        # only once
        res = self.client.post(f"/api/tasks/{task_id}/estimate/", {"minutes": 300}, format="json")
        self.assertEqual(res.status_code, 400)
        # logged for the review meeting
        acts = self.client.get("/api/task-activities/").data["results"]
        self.assertTrue(any("240 min (assigner said: 60 min)" in a["text"] for a in acts))

    def test_only_assignee_estimates(self):
        task_id = self.create_task(self.manager, self.rahul).data["id"]
        self.as_(self.amit)
        # amit can't even see this task -> 404; the rule holds either way
        self.assertIn(self.client.post(f"/api/tasks/{task_id}/estimate/",
                                       {"minutes": 60}, format="json").status_code, (403, 404))


class RecurrenceEndTests(Base):
    """A3: repeat_until stops the spawning."""

    def test_recurrence_stops_after_end_date(self):
        due = timezone.now() + timedelta(hours=1)
        task = Task.objects.create(
            title="Daily report", assigned_to=self.rahul, created_by=self.manager,
            frequency="daily", due_at=due,
            repeat_until=timezone.localtime(due).date())      # ends TODAY
        self.as_(self.rahul)
        self.client.post(f"/api/tasks/{task.id}/complete/",
                         {"remarks": "done for today", "actual_minutes": 20}, format="json")
        self.assertEqual(Task.objects.filter(title="Daily report").count(), 1)  # no next

    def test_recurrence_continues_within_end_date(self):
        due = timezone.now() + timedelta(hours=1)
        task = Task.objects.create(
            title="Daily report", assigned_to=self.rahul, created_by=self.manager,
            frequency="daily", due_at=due, effort_minutes=30,
            repeat_until=(timezone.localtime(due) + timedelta(days=5)).date())
        self.as_(self.rahul)
        self.client.post(f"/api/tasks/{task.id}/complete/",
                         {"remarks": "done for today", "actual_minutes": 20}, format="json")
        nxt = Task.objects.filter(title="Daily report").exclude(pk=task.pk).get()
        self.assertEqual(nxt.effort_minutes, 30)               # effort carries over
        self.assertEqual(nxt.repeat_until, task.repeat_until)
        self.assertIsNone(nxt.actual_minutes)                  # fresh occurrence, fresh clock


class SoftDeleteTests(Base):
    """A4: Deleted Tasks bin."""

    def test_delete_is_soft_admin_only_and_restorable(self):
        task = Task.objects.create(title="X", assigned_to=self.rahul, created_by=self.manager)
        self.as_(self.manager)
        self.assertEqual(self.client.delete(f"/api/tasks/{task.id}/").status_code, 403)
        self.as_(self.admin)
        self.assertEqual(self.client.delete(f"/api/tasks/{task.id}/").status_code, 204)
        task.refresh_from_db()
        self.assertIsNotNone(task.deleted_at)                  # still in the DB
        # hidden from normal lists...
        self.as_(self.rahul)
        self.assertEqual(len(self.client.get("/api/tasks/?scope=my").data["results"]), 0)
        # ...but in the admin bin
        self.as_(self.admin)
        binned = self.client.get("/api/tasks/?scope=deleted").data["results"]
        self.assertEqual([t["id"] for t in binned], [task.id])
        # restore
        self.assertEqual(self.client.post(f"/api/tasks/{task.id}/restore/").status_code, 200)
        task.refresh_from_db()
        self.assertIsNone(task.deleted_at)

    def test_deleted_bin_is_admin_only(self):
        self.as_(self.manager)
        self.assertEqual(self.client.get("/api/tasks/?scope=deleted").status_code, 403)

    def test_deleted_tasks_send_no_reminders(self):
        from .reminders import send_task_reminders
        Task.objects.create(title="Late", assigned_to=self.rahul,
                            due_at=timezone.now() - timedelta(hours=1),
                            deleted_at=timezone.now())
        self.assertEqual(send_task_reminders(), 0)


class LockdownTests(Base):
    """B1: assignee = status only; creator = nothing direct; admin = full."""

    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(
            title="Original", assigned_to=self.rahul, created_by=self.manager,
            due_at=timezone.now() + timedelta(days=1), effort_minutes=60)

    def test_assignee_can_move_status(self):
        self.as_(self.rahul)
        res = self.client.patch(f"/api/tasks/{self.task.id}/", {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)

    def test_assignee_cannot_touch_other_fields(self):
        self.as_(self.rahul)
        for body in ({"title": "Hacked"}, {"due_at": (timezone.now() + timedelta(days=30)).isoformat()},
                     {"effort_minutes": 5}, {"priority": "low"}):
            res = self.client.patch(f"/api/tasks/{self.task.id}/", body, format="json")
            self.assertEqual(res.status_code, 403, body)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Original")

    def test_creator_cannot_edit_directly_anymore(self):
        self.as_(self.manager)
        res = self.client.patch(f"/api/tasks/{self.task.id}/", {"due_at": timezone.now().isoformat()},
                                format="json")
        self.assertEqual(res.status_code, 403)
        self.assertIn("Request change", res.data["detail"])

    def test_admin_full_edit_is_logged(self):
        self.as_(self.admin)
        res = self.client.patch(f"/api/tasks/{self.task.id}/", {"title": "Fixed by admin"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.as_(self.rahul)
        acts = self.client.get("/api/task-activities/").data["results"]
        self.assertTrue(any("Edited directly by admin" in a["text"] for a in acts))


class ChangeRequestTests(Base):
    """B2: the Modification Request workflow."""

    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(
            title="Report", assigned_to=self.rahul, created_by=self.manager,
            due_at=timezone.now() + timedelta(days=1), frequency="daily")

    def raise_request(self, as_user, changes, reason="the deadline moved"):
        self.as_(as_user)
        return self.client.post(f"/api/tasks/{self.task.id}/request_change/",
                                {"changes": changes, "reason": reason}, format="json")

    def test_assignee_request_goes_to_creator_and_creator_approves(self):
        new_due = (timezone.now() + timedelta(days=3)).isoformat()
        res = self.raise_request(self.rahul, {"due_at": new_due})
        self.assertEqual(res.status_code, 201)
        # creator notified
        self.assertTrue(Notification.objects.filter(user=self.manager,
                                                    type="task_change_request").exists())
        # creator's inbox has it
        self.as_(self.manager)
        inbox = self.client.get("/api/task-change-requests/?scope=inbox").data["results"]
        self.assertEqual(len(inbox), 1)
        rid = inbox[0]["id"]
        approved = self.client.post(f"/api/task-change-requests/{rid}/review/",
                                    {"decision": "approved", "remarks": "ok"}, format="json")
        self.assertEqual(approved.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.due_at.isoformat()[:16], new_due[:16])   # applied
        # requester notified of the outcome
        self.assertTrue(Notification.objects.filter(user=self.rahul,
                                                    type="task_change_reviewed").exists())
        # admin got the audit log notification
        self.assertTrue(Notification.objects.filter(user=self.admin,
                                                    type="task_change_log").exists())

    def test_creator_request_falls_back_to_admin_without_a_manager(self):
        """Last resort only: meera has no "Reports to" on file, so there is
        nobody one step up and an admin has to decide."""
        self.assertIsNone(self.manager.reporting_manager)
        res = self.raise_request(self.manager, {"frequency": "one_time"},
                                 "accidentally made it daily")
        self.assertEqual(res.status_code, 201)
        rid = res.data["id"]
        # creator cannot approve their own request
        self.as_(self.manager)
        self.assertEqual(self.client.post(f"/api/task-change-requests/{rid}/review/",
                                          {"decision": "approved"}, format="json").status_code, 403)
        # admin got it and approves
        self.assertTrue(Notification.objects.filter(user=self.admin,
                                                    type="task_change_request").exists())
        self.as_(self.admin)
        self.assertEqual(self.client.post(f"/api/task-change-requests/{rid}/review/",
                                          {"decision": "approved"}, format="json").status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.frequency, "one_time")        # daily mistake stopped

    def test_creator_request_goes_to_their_manager_not_admin(self):
        """The reviewer's rule: one step up, never a broadcast to admins.
        meera created the task herself, so her own reporting manager decides
        and no admin is pulled in."""
        boss = make("dept_head", Role.SALES_MANAGER)
        self.manager.reporting_manager = boss
        self.manager.save(update_fields=["reporting_manager"])

        res = self.raise_request(self.manager, {"frequency": "one_time"},
                                 "accidentally made it daily")
        self.assertEqual(res.status_code, 201)
        rid = res.data["id"]
        self.assertTrue(Notification.objects.filter(
            user=boss, type="task_change_request").exists())
        self.assertFalse(Notification.objects.filter(
            user=self.admin, type="task_change_request").exists())

        # it sits in the manager's inbox, not in an admin's
        self.as_(boss)
        inbox = self.client.get("/api/task-change-requests/?scope=inbox").data
        self.assertIn(rid, [r["id"] for r in inbox["results"]])
        self.as_(self.admin)
        inbox = self.client.get("/api/task-change-requests/?scope=inbox").data
        self.assertNotIn(rid, [r["id"] for r in inbox["results"]])

        self.as_(boss)
        self.assertEqual(self.client.post(f"/api/task-change-requests/{rid}/review/",
                                          {"decision": "approved"}, format="json").status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.frequency, "one_time")

    def test_assignee_request_never_reaches_admin(self):
        """The person who GAVE the task decides -- admins stay out of it."""
        res = self.raise_request(self.rahul, {"priority": "high"},
                                 "customer wants it today")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(Notification.objects.filter(
            user=self.manager, type="task_change_request").exists())
        self.assertFalse(Notification.objects.filter(
            user=self.admin, type="task_change_request").exists())
        self.as_(self.admin)
        ids = [r["id"] for r in
               self.client.get("/api/task-change-requests/?scope=inbox").data["results"]]
        self.assertNotIn(res.data["id"], ids)

    def test_rejection_changes_nothing(self):
        old_due = self.task.due_at
        res = self.raise_request(self.rahul, {"due_at": (timezone.now() + timedelta(days=9)).isoformat()})
        self.as_(self.manager)
        self.client.post(f"/api/task-change-requests/{res.data['id']}/review/",
                         {"decision": "rejected", "remarks": "no"}, format="json")
        self.task.refresh_from_db()
        self.assertEqual(self.task.due_at, old_due)

    def test_cancel_change_soft_deletes(self):
        res = self.raise_request(self.manager, {"cancel": True}, "task no longer needed")
        self.as_(self.admin)
        self.client.post(f"/api/task-change-requests/{res.data['id']}/review/",
                         {"decision": "approved"}, format="json")
        self.task.refresh_from_db()
        self.assertIsNotNone(self.task.deleted_at)

    def test_outsider_cannot_request_and_bad_fields_rejected(self):
        self.assertEqual(self.raise_request(self.amit, {"title": "x"}).status_code, 404)  # can't even see it
        # status can NEVER be changed via request -- completing is the
        # assignee's own scored action, not something to be "approved" in
        res = self.raise_request(self.rahul, {"status": "done"})
        self.assertEqual(res.status_code, 400)
        res = self.raise_request(self.rahul, {})
        self.assertEqual(res.status_code, 400)

    def test_reassignment_via_request(self):
        res = self.raise_request(self.rahul, {"assigned_to": self.amit.id},
                                 "Amit knows this customer better")
        self.assertEqual(res.status_code, 201)
        self.as_(self.manager)
        self.client.post(f"/api/task-change-requests/{res.data['id']}/review/",
                         {"decision": "approved"}, format="json")
        self.task.refresh_from_db()
        self.assertEqual(self.task.assigned_to, self.amit)
        self.assertTrue(Notification.objects.filter(user=self.amit, type="task_assigned").exists())

    def test_double_review_blocked(self):
        res = self.raise_request(self.rahul, {"priority": "low"})
        self.as_(self.manager)
        rid = res.data["id"]
        self.client.post(f"/api/task-change-requests/{rid}/review/", {"decision": "approved"}, format="json")
        self.assertEqual(self.client.post(f"/api/task-change-requests/{rid}/review/",
                                          {"decision": "rejected"}, format="json").status_code, 400)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class CompletionEvidenceTests(Base):
    """B3: mandatory remarks / attachment on completion."""

    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(title="Daily tick", assigned_to=self.rahul,
                                        created_by=self.manager)

    def set_policy(self, remarks=False, attachment=False):
        cfg = TaskSettings.get()
        cfg.require_completion_remarks = remarks
        cfg.require_completion_attachment = attachment
        cfg.save()

    def test_plain_tick_always_asks_for_description_now(self):
        # P2: description is mandatory on EVERY completion — the plain PATCH
        # path answers 400 so the UI opens the completion modal.
        self.as_(self.rahul)
        res = self.client.patch(f"/api/tasks/{self.task.id}/", {"status": "done"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data.get("needs"), "remarks")

    def test_complete_needs_description_and_actual_minutes(self):
        self.as_(self.rahul)
        # description alone is not enough — actual effort spent is mandatory
        res = self.client.post(f"/api/tasks/{self.task.id}/complete/",
                               {"remarks": "Filled and delivered the bottle"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data.get("needs"), "actual_minutes")
        res = self.client.post(f"/api/tasks/{self.task.id}/complete/",
                               {"remarks": "Filled and delivered the bottle",
                                "actual_minutes": 45}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["completion_note"], "Filled and delivered the bottle")
        self.assertEqual(res.data["actual_minutes"], 45)
        self.assertEqual(res.data["progress_percent"], 100)

    def test_attachment_required(self):
        self.set_policy(attachment=True)
        self.as_(self.rahul)
        res = self.client.post(f"/api/tasks/{self.task.id}/complete/",
                               {"remarks": "done", "actual_minutes": 10}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data.get("needs"), "attachment")
        res = self.client.post(
            f"/api/tasks/{self.task.id}/complete/",
            {"remarks": "done", "actual_minutes": 10,
             "file": SimpleUploadedFile("proof.jpg", b"jpegbytes")},
            format="multipart")
        self.assertEqual(res.status_code, 200)
        files = self.client.get(f"/api/tasks/{self.task.id}/files/").data
        self.assertEqual(files[0]["filename"], "proof.jpg")

    def test_settings_write_is_admin_only_read_is_open(self):
        self.as_(self.rahul)
        self.assertEqual(self.client.get("/api/task-settings/").status_code, 200)
        self.assertEqual(self.client.post("/api/task-settings/",
                                          {"require_completion_remarks": True},
                                          format="json").status_code, 403)
        self.as_(self.admin)
        res = self.client.post("/api/task-settings/",
                               {"require_completion_remarks": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["require_completion_remarks"])


class PastDeadlineTests(Base):
    """A real slip on 03 Sep: a manager assigning at 11 AM set the deadline to
    5:00 AM instead of 5:00 PM. The task saved silently and was born overdue.
    A deadline in the past is never intentional, so both doors refuse it."""

    def test_creating_with_a_past_deadline_is_rejected(self):
        res = self.create_task(
            self.manager, self.rahul,
            due_at=(timezone.now() - timedelta(hours=6)).isoformat())
        self.assertEqual(res.status_code, 400)
        self.assertIn("AM/PM", str(res.data["due_at"]))

    def test_the_message_names_the_time_twelve_hours_on(self):
        """5:00 AM was typed; the hint has to say 5:00 PM or it is no help."""
        five_am = timezone.localtime(timezone.now()).replace(
            hour=5, minute=0, second=0, microsecond=0)
        if five_am >= timezone.localtime(timezone.now()):
            five_am -= timedelta(days=1)
        res = self.create_task(self.manager, self.rahul, due_at=five_am.isoformat())
        self.assertEqual(res.status_code, 400)
        self.assertIn("05:00 PM", str(res.data["due_at"]))

    def test_a_deadline_minutes_ahead_still_saves(self):
        """Only the past is refused -- a genuinely tight deadline is allowed."""
        res = self.create_task(
            self.manager, self.rahul,
            due_at=(timezone.now() + timedelta(minutes=20)).isoformat())
        self.assertEqual(res.status_code, 201)

    def test_change_request_cannot_move_a_deadline_into_the_past(self):
        task = Task.objects.create(
            title="Report", assigned_to=self.rahul, created_by=self.manager,
            due_at=timezone.now() + timedelta(days=1))
        self.as_(self.rahul)
        res = self.client.post(
            f"/api/tasks/{task.id}/request_change/",
            {"changes": {"due_at": (timezone.now() - timedelta(hours=2)).isoformat()},
             "reason": "the deadline moved"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("AM/PM", str(res.data))


class HrManagerAssignTests(Base):
    """HR runs company-wide processes (induction, documents, PIP follow-ups),
    so the HR Manager assigns like any other manager -- but level 2 still
    stops at the admins."""

    def test_hr_manager_can_assign_to_staff(self):
        res = self.create_task(self.hr, self.rahul)
        self.assertEqual(res.status_code, 201)

    def test_hr_manager_can_assign_across_departments(self):
        res = self.create_task(self.hr, self.vikram)     # hr -> purchase
        self.assertEqual(res.status_code, 201)

    def test_hr_manager_can_assign_to_a_fellow_manager(self):
        res = self.create_task(self.hr, self.manager)
        self.assertEqual(res.status_code, 201)

    def test_hr_manager_still_cannot_assign_to_an_admin(self):
        res = self.create_task(self.hr, self.admin)
        self.assertEqual(res.status_code, 403)   # authority, not bad input

    def test_hr_manager_sees_the_tasks_they_gave_out(self):
        self.create_task(self.hr, self.rahul, title="Collect PAN card")
        self.as_(self.hr)
        titles = [t["title"] for t in self.client.get("/api/tasks/").data["results"]]
        self.assertIn("Collect PAN card", titles)

    def test_admin_is_not_offered_in_the_hr_assignee_list(self):
        self.as_(self.hr)
        ids = {u["id"] for u in self.client.get("/api/tasks/assignees/").data}
        self.assertIn(self.rahul.id, ids)
        self.assertNotIn(self.admin.id, ids)


class ProofreadTests(Base):
    """The browser underlines a misspelling but only offers the fix on
    right-click, which nobody finds. This endpoint is that fix as a button."""

    def test_empty_text_is_rejected(self):
        self.as_(self.rahul)
        res = self.client.post("/api/tasks/proofread/", {"text": "   "}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_very_long_text_is_rejected(self):
        self.as_(self.rahul)
        res = self.client.post("/api/tasks/proofread/", {"text": "a" * 4001}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_with_ai_off_the_text_comes_back_untouched(self):
        """AI is off in tests. A proofreader that cannot reach the model must
        hand back what it was given -- never an error, never an empty box."""
        self.as_(self.rahul)
        res = self.client.post("/api/tasks/proofread/",
                               {"text": "chek the invoce"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["text"], "chek the invoce")
        self.assertFalse(res.data["changed"])

    def test_a_rewritten_reply_is_thrown_away(self):
        """A model that rewrites instead of proofreading is worse than none.
        Anything wildly longer or shorter is refused and the original kept."""
        from unittest import mock
        with mock.patch("crm.ai_tasks.llm.chat", return_value="Hi."):
            self.as_(self.rahul)
            long_text = "Please chek the invoce of Ravi and send the quatation tommorow."
            res = self.client.post("/api/tasks/proofread/",
                                   {"text": long_text}, format="json")
        self.assertEqual(res.data["text"], long_text)
        self.assertFalse(res.data["changed"])

    def test_a_genuine_correction_is_returned(self):
        from unittest import mock
        fixed = "Check the invoice."
        with mock.patch("crm.ai_tasks.llm.chat", return_value=fixed):
            self.as_(self.rahul)
            res = self.client.post("/api/tasks/proofread/",
                                   {"text": "chek the invoce."}, format="json")
        self.assertEqual(res.data["text"], fixed)
        self.assertTrue(res.data["changed"])

    def test_line_breaks_survive(self):
        from unittest import mock
        text = "Call the vendor.\nConfirm the delivery date."
        with mock.patch("crm.ai_tasks.llm.chat", return_value=text):
            self.as_(self.rahul)
            res = self.client.post("/api/tasks/proofread/",
                                   {"text": "Call the vender.\nConfrim the delivery date."},
                                   format="json")
        self.assertEqual(res.data["text"].count("\n"), 1)


class VoiceNoteTests(Base):
    """T-00136: speak a task, get the form filled in.

    The model hears words. It never picks a user id and never creates a task,
    because a misheard name would quietly become somebody else's work. These
    tests pin that split: whatever the model says, the SERVER decides who the
    person is and whether the deadline is usable.
    """

    URL = "/api/tasks/voice_draft/"

    def clip(self, name="note.webm"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, b"x" * 4096, content_type="audio/webm")

    def draft(self, transcript, ai_reply, as_user=None):
        """Run the endpoint with transcription and drafting both stubbed."""
        from unittest import mock
        self.as_(as_user or self.manager)
        with mock.patch("config.llm.can_transcribe", return_value=True), \
             mock.patch("config.llm.transcribe", return_value=transcript), \
             mock.patch("crm.ai_tasks.llm.chat_json", return_value=ai_reply):
            return self.client.post(self.URL, {"audio": self.clip()}, format="multipart")

    # ---- what it gets right ------------------------------------------------
    def test_a_named_person_is_matched_to_a_real_user(self):
        res = self.draft("Rahul ko quotation bhejna hai",
                         {"title": "Send the quotation", "assignee": "rahul"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["assigned_to"], self.rahul.id)
        self.assertIsNone(res.data["assignee_heard"])

    def test_a_first_name_is_enough(self):
        res = self.draft("Amit ko bolo", {"title": "Tell Amit", "assignee": "Amit"})
        self.assertEqual(res.data["assigned_to"], self.amit.id)

    def test_the_transcript_comes_back_so_it_can_be_read(self):
        res = self.draft("stock check karna hai", {"title": "Stock check"})
        self.assertEqual(res.data["transcript"], "stock check karna hai")

    def test_a_future_deadline_is_kept(self):
        soon = (timezone.now() + timedelta(days=1)).isoformat()
        res = self.draft("kal tak", {"title": "T", "due_at": soon})
        self.assertIsNotNone(res.data["due_at"])
        self.assertIsNone(res.data["due_heard"])

    # ---- what it refuses to guess -----------------------------------------
    def test_an_unknown_name_is_reported_not_guessed(self):
        res = self.draft("Ramesh ko bolo", {"title": "T", "assignee": "Ramesh"})
        self.assertIsNone(res.data["assigned_to"])
        self.assertEqual(res.data["assignee_heard"], "Ramesh")

    def test_a_past_deadline_is_dropped_and_flagged(self):
        """The same AM/PM trap as the typed form: 5 PM heard as 5 AM."""
        past = (timezone.now() - timedelta(hours=6)).isoformat()
        res = self.draft("paanch baje tak", {"title": "T", "due_at": past})
        self.assertIsNone(res.data["due_at"])
        self.assertEqual(res.data["due_heard"], past)

    def test_a_name_above_the_speakers_level_is_not_matched(self):
        """An employee speaking their boss's name must not gain the power to
        task them -- the level rule applies to speech exactly as to typing."""
        res = self.draft("boss ko bolo", {"title": "T", "assignee": "boss"},
                         as_user=self.rahul)
        self.assertIsNone(res.data["assigned_to"])
        self.assertEqual(res.data["assignee_heard"], "boss")

    def two_rahuls(self):
        """The fixture user is literally called "rahul", which would be an
        exact match; give everyone a surname so only the first name is shared."""
        from accounts.models import Role
        User.objects.filter(pk=self.rahul.pk).update(first_name="Rahul", last_name="Sinha")
        make("rahul.b", Role.SALES_EXECUTIVE)
        User.objects.filter(username="rahul.b").update(first_name="Rahul", last_name="Tyagi")

    def test_a_shared_first_name_is_left_for_the_human(self):
        """Two Rahuls and no surname spoken: we do not know which one."""
        self.two_rahuls()
        res = self.draft("Rahul ko bolo", {"title": "T", "assignee": "Rahul"})
        self.assertIsNone(res.data["assigned_to"])
        self.assertEqual(res.data["assignee_heard"], "Rahul")

    def test_the_surname_settles_it(self):
        self.two_rahuls()
        res = self.draft("Rahul Tyagi ko bolo", {"title": "T", "assignee": "Rahul Tyagi"})
        self.assertEqual(res.data["assigned_to"], User.objects.get(username="rahul.b").id)

    def test_two_people_with_the_identical_name_match_neither(self):
        from accounts.models import Role
        for u in ("twin.a", "twin.b"):
            make(u, Role.SALES_EXECUTIVE)
            User.objects.filter(username=u).update(first_name="Amit", last_name="Kumar")
        res = self.draft("Amit Kumar ko bolo", {"title": "T", "assignee": "Amit Kumar"})
        self.assertIsNone(res.data["assigned_to"])

    def test_nothing_is_created(self):
        before = Task.objects.count()
        self.draft("koi task banao", {"title": "Something", "assignee": "rahul"})
        self.assertEqual(Task.objects.count(), before)

    # ---- refusals ----------------------------------------------------------
    def test_no_audio_is_rejected(self):
        self.as_(self.manager)
        self.assertEqual(self.client.post(self.URL, {}, format="multipart").status_code, 400)

    def test_a_huge_clip_is_rejected(self):
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.as_(self.manager)
        big = SimpleUploadedFile("big.webm", b"x" * (11 * 1024 * 1024),
                                 content_type="audio/webm")
        with mock.patch("config.llm.can_transcribe", return_value=True):
            res = self.client.post(self.URL, {"audio": big}, format="multipart")
        self.assertEqual(res.status_code, 400)

    def test_it_says_so_when_voice_is_not_configured(self):
        from unittest import mock
        self.as_(self.manager)
        with mock.patch("config.llm.can_transcribe", return_value=False):
            res = self.client.post(self.URL, {"audio": self.clip()}, format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Type the task instead", str(res.data))

    def test_unintelligible_audio_asks_for_another_go(self):
        from unittest import mock
        self.as_(self.manager)
        with mock.patch("config.llm.can_transcribe", return_value=True), \
             mock.patch("config.llm.transcribe", return_value=None):
            res = self.client.post(self.URL, {"audio": self.clip()}, format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("quieter", str(res.data))


class CompletionApprovalTests(Base):
    """Founders Desk, 05 Sep: the giver accepts or rejects the finished work,
    and a rejection puts the task back.

    Deliberately NOT a fourth task status: the task completes as before and a
    review is raised beside it. That also decides who carries a slow approver
    -- the work counts as done from the moment it was submitted, so nobody is
    marked late because their manager sat on the review.
    """

    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(
            title="Send the quotation", assigned_to=self.rahul, created_by=self.manager,
            effort_minutes=60, due_at=timezone.now() + timedelta(days=1))

    def finish(self, who=None, remarks="Sent it and confirmed on call"):
        self.as_(who or self.rahul)
        return self.client.post(f"/api/tasks/{self.task.id}/complete/",
                                {"remarks": remarks, "actual_minutes": 45}, format="json")

    def pending(self):
        from .models import TaskCompletion
        return TaskCompletion.objects.filter(task=self.task, status="pending").first()

    # ---- raising it -------------------------------------------------------
    def test_finishing_asks_the_giver_to_accept(self):
        self.assertEqual(self.finish().status_code, 200)
        c = self.pending()
        self.assertIsNotNone(c)
        self.assertEqual(c.approver, self.manager)
        self.assertEqual(c.submitted_by, self.rahul)

    def test_the_giver_is_told(self):
        self.finish()
        self.assertTrue(Notification.objects.filter(
            user=self.manager, type="task_completion_review").exists())

    def test_the_task_is_done_while_the_review_waits(self):
        """An assignee must not be marked late because the reviewer is slow."""
        self.finish()
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.DONE)

    def test_your_own_task_needs_nobody(self):
        mine = Task.objects.create(title="Mine", assigned_to=self.rahul,
                                   created_by=self.rahul, effort_minutes=30,
                                   due_at=timezone.now() + timedelta(days=1))
        self.as_(self.rahul)
        self.client.post(f"/api/tasks/{mine.id}/complete/",
                         {"remarks": "did it myself", "actual_minutes": 10}, format="json")
        from .models import TaskCompletion
        self.assertFalse(TaskCompletion.objects.filter(task=mine).exists())

    # ---- accepting --------------------------------------------------------
    def test_accepting_leaves_the_task_done(self):
        self.finish()
        c = self.pending()
        self.as_(self.manager)
        res = self.client.post(f"/api/task-completions/{c.id}/review/",
                               {"decision": "approved"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.DONE)
        self.assertTrue(Notification.objects.filter(
            user=self.rahul, type="task_completion_accepted").exists())

    # ---- rejecting --------------------------------------------------------
    def test_rejecting_reopens_the_task(self):
        self.finish()
        c = self.pending()
        self.as_(self.manager)
        res = self.client.post(f"/api/task-completions/{c.id}/review/",
                               {"decision": "rejected",
                                "remarks": "The invoice copy is missing"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.OPEN)
        self.assertIsNone(self.task.completed_at)

    def test_rejecting_needs_a_reason(self):
        """"Redo it" with no reason wastes the second attempt too."""
        self.finish()
        c = self.pending()
        self.as_(self.manager)
        res = self.client.post(f"/api/task-completions/{c.id}/review/",
                               {"decision": "rejected", "remarks": "no"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("remarks", res.data)

    def test_the_doer_is_told_what_to_fix(self):
        self.finish()
        c = self.pending()
        self.as_(self.manager)
        self.client.post(f"/api/task-completions/{c.id}/review/",
                         {"decision": "rejected", "remarks": "The invoice copy is missing"},
                         format="json")
        n = Notification.objects.filter(user=self.rahul,
                                        type="task_completion_rejected").first()
        self.assertIsNotNone(n)
        self.assertIn("invoice copy is missing", n.body)

    def test_a_rejected_task_stops_counting_as_completed(self):
        from .scoring import score_for
        self.finish()
        self.assertEqual(score_for(self.rahul)["completed"], 1)
        c = self.pending()
        self.as_(self.manager)
        self.client.post(f"/api/task-completions/{c.id}/review/",
                         {"decision": "rejected", "remarks": "Not what was asked for"},
                         format="json")
        self.assertEqual(score_for(self.rahul)["completed"], 0)

    def test_it_can_be_finished_again_after_a_rejection(self):
        from .models import TaskCompletion
        self.finish()
        c = self.pending()
        self.as_(self.manager)
        self.client.post(f"/api/task-completions/{c.id}/review/",
                         {"decision": "rejected", "remarks": "Attach the invoice copy"},
                         format="json")
        self.assertEqual(self.finish(remarks="Invoice attached this time").status_code, 200)
        self.assertEqual(TaskCompletion.objects.filter(task=self.task).count(), 2)
        self.assertEqual(TaskCompletion.objects.filter(task=self.task,
                                                       status="pending").count(), 1)

    # ---- who may decide ---------------------------------------------------
    def test_the_doer_cannot_accept_their_own_work(self):
        self.finish()
        c = self.pending()
        self.as_(self.rahul)
        res = self.client.post(f"/api/task-completions/{c.id}/review/",
                               {"decision": "approved"}, format="json")
        self.assertIn(res.status_code, (403, 404))

    def test_a_bystander_cannot_decide(self):
        self.finish()
        c = self.pending()
        self.as_(self.amit)
        res = self.client.post(f"/api/task-completions/{c.id}/review/",
                               {"decision": "approved"}, format="json")
        self.assertIn(res.status_code, (403, 404))

    def test_it_cannot_be_decided_twice(self):
        self.finish()
        c = self.pending()
        self.as_(self.manager)
        self.client.post(f"/api/task-completions/{c.id}/review/",
                         {"decision": "approved"}, format="json")
        res = self.client.post(f"/api/task-completions/{c.id}/review/",
                               {"decision": "rejected", "remarks": "changed my mind"},
                               format="json")
        self.assertEqual(res.status_code, 400)

    def test_the_inbox_shows_only_what_is_mine_to_decide(self):
        self.finish()
        self.as_(self.manager)
        self.assertEqual(len(self.client.get("/api/task-completions/?scope=inbox").data["results"]), 1)
        self.as_(self.amit)
        self.assertEqual(len(self.client.get("/api/task-completions/?scope=inbox").data["results"]), 0)
