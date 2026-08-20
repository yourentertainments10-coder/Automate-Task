"""Mistake Register M1: logging, 3-level accountability, repeat confirmation,
SLA escalation, task integration, SOP verdicts, permissions."""
from datetime import timedelta

from django.utils import timezone

from crm.models import Task, TaskStatus
from crm.tests_task_engine import Base
from notifications.models import Notification

from .models import Mistake, MistakeCategory, MistakeStatus
from .sla import escalate_overdue_mistakes


class MistakeBase(Base):
    def setUp(self):
        super().setUp()
        # rahul reports to meera; meera reports to boss (dept-head chain)
        self.rahul.reporting_manager = self.manager
        self.rahul.save(update_fields=["reporting_manager"])
        self.manager.reporting_manager = self.admin
        self.manager.save(update_fields=["reporting_manager"])

    def log_mistake(self, as_user, employee, **extra):
        self.as_(as_user)
        body = {"employee": employee.id, "category": "Wrong Part Number",
                "severity": "medium", "description": "Wrong Hyundai part ordered",
                **extra}
        return self.client.post("/api/mistakes/", body, format="json")


class RegisterTests(MistakeBase):
    def test_seeded_categories_available(self):
        self.as_(self.rahul)
        names = [c["name"] for c in self.client.get("/api/mistake-categories/").data]
        self.assertIn("Wrong Part Number", names)
        self.assertIn("SOP Violation", names)
        self.assertEqual(len(names), 29)

    def test_log_sets_manager_sla_and_notifies(self):
        res = self.log_mistake(self.manager, self.rahul)
        self.assertEqual(res.status_code, 201)
        m = Mistake.objects.get(pk=res.data["id"])
        self.assertEqual(m.manager, self.manager)          # accountable
        self.assertEqual(m.department, "sales")
        self.assertIsNotNone(m.sla_due_at)                 # 48h for medium
        self.assertTrue(Notification.objects.filter(
            user=self.rahul, type="mistake_logged").exists())
        # medium severity: founder NOT pinged
        self.assertFalse(Notification.objects.filter(
            user=self.admin, type="mistake_logged").exists())

    def test_high_severity_reaches_founder(self):
        self.log_mistake(self.manager, self.rahul, severity="high")
        self.assertTrue(Notification.objects.filter(
            user=self.admin, type="mistake_logged").exists())

    def test_unknown_category_rejected_and_employee_cannot_log_for_others(self):
        res = self.log_mistake(self.manager, self.rahul, category="Nonsense")
        self.assertEqual(res.status_code, 400)
        res = self.log_mistake(self.amit, self.rahul)      # peer, no tasks.assign
        self.assertEqual(res.status_code, 403)

    def test_employee_sees_own_only_manager_sees_department(self):
        self.log_mistake(self.manager, self.rahul)
        self.log_mistake(self.admin, self.vikram)          # purchase
        self.as_(self.rahul)
        rows = self.client.get("/api/mistakes/").data["results"]
        self.assertEqual(len(rows), 1)
        self.as_(self.manager)                             # sales manager
        codes = [r["employee_detail"]["username"] for r in
                 self.client.get("/api/mistakes/").data["results"]]
        self.assertIn("rahul", codes)
        self.assertNotIn("vikram", codes)


class ThreeLevelTests(MistakeBase):
    def test_explain_requires_structured_root_cause(self):
        mid = self.log_mistake(self.manager, self.rahul).data["id"]
        self.as_(self.rahul)
        res = self.client.post(f"/api/mistakes/{mid}/explain/",
                               {"explanation": "Mistake happened."}, format="json")
        self.assertEqual(res.status_code, 400)             # no root cause picked
        res = self.client.post(f"/api/mistakes/{mid}/explain/",
                               {"explanation": "Catalogue was outdated",
                                "root_cause": "wrong_information",
                                "corrective_action": "Re-ordered correct part"},
                               format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "explained")

    def test_repeat_confirmation_makes_level2_with_mandatory_capa(self):
        first = self.log_mistake(self.manager, self.rahul).data["id"]
        second = self.log_mistake(self.manager, self.rahul).data["id"]
        # the detail view suggests the earlier one to the manager
        detail = self.client.get(f"/api/mistakes/{second}/").data
        self.assertEqual(detail["possible_repeats"][0]["id"], first)
        res = self.client.post(f"/api/mistakes/{second}/confirm_repeat/",
                               {"same": True, "repeat_of": first}, format="json")
        self.assertEqual(res.data["occurrence_level"], 2)
        self.assertTrue(Notification.objects.filter(
            user=self.rahul, type="mistake_repeat",
            title__startswith="REPEAT ERROR").exists())
        # level 2: explanation without preventive action is refused
        self.as_(self.rahul)
        res = self.client.post(f"/api/mistakes/{second}/explain/",
                               {"explanation": "x", "root_cause": "human_error",
                                "corrective_action": "y"}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.post(f"/api/mistakes/{second}/explain/",
                               {"explanation": "x", "root_cause": "human_error",
                                "corrective_action": "y", "preventive_action": "z"},
                               format="json")
        self.assertEqual(res.status_code, 200)

    def test_third_occurrence_escalates_to_dept_head(self):
        first = self.log_mistake(self.manager, self.rahul).data["id"]
        Mistake.objects.filter(pk=first).update(occurrence_level=2)
        third = self.log_mistake(self.manager, self.rahul).data["id"]
        self.client.post(f"/api/mistakes/{third}/confirm_repeat/",
                         {"same": True, "repeat_of": first}, format="json")
        m = Mistake.objects.get(pk=third)
        self.assertEqual(m.occurrence_level, 3)
        self.assertEqual(m.escalation_level, 1)
        # dept head (= meera's manager = boss/admin) got the escalation
        self.assertTrue(Notification.objects.filter(
            user=self.admin, type="mistake_escalated",
            title__startswith="THIRD OCCURRENCE").exists())
        # resolving a level-3 without a decided human action is refused
        self.as_(self.manager)
        res = self.client.post(f"/api/mistakes/{third}/review/",
                               {"resolve": True, "manager_remarks": "ok",
                                "classification": "human"}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.post(f"/api/mistakes/{third}/review/",
                               {"resolve": True, "manager_remarks": "retraining planned",
                                "classification": "human",
                                "level3_action": "retraining"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "resolved")

    def test_manager_cannot_just_click_close(self):
        mid = self.log_mistake(self.manager, self.rahul).data["id"]
        res = self.client.post(f"/api/mistakes/{mid}/review/",
                               {"resolve": True}, format="json")
        self.assertEqual(res.status_code, 400)             # remarks + classification needed

    def test_sop_adequate_no_recorded_as_process_problem(self):
        mid = self.log_mistake(self.manager, self.rahul).data["id"]
        res = self.client.post(f"/api/mistakes/{mid}/review/",
                               {"sop_name": "Parts ordering SOP", "sop_followed": True,
                                "sop_adequate": False, "classification": "process",
                                "manager_remarks": "SOP has no verification step",
                                "resolve": True}, format="json")
        self.assertEqual(res.status_code, 200)
        m = Mistake.objects.get(pk=mid)
        self.assertFalse(m.sop_adequate)
        self.assertEqual(m.classification, "process")      # process, not the person


class SlaEscalationTests(MistakeBase):
    def test_missed_sla_climbs_the_chain(self):
        mid = self.log_mistake(self.manager, self.rahul).data["id"]
        Mistake.objects.filter(pk=mid).update(
            sla_due_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(escalate_overdue_mistakes(), 1)
        m = Mistake.objects.get(pk=mid)
        self.assertEqual(m.escalation_level, 1)            # -> dept head
        self.assertGreater(m.sla_due_at, timezone.now())   # clock re-armed
        self.assertTrue(Notification.objects.filter(
            user=self.admin, type="mistake_escalated",
            title__startswith="SLA MISSED").exists())
        # second miss -> founder tier, then it stops climbing
        Mistake.objects.filter(pk=mid).update(
            sla_due_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(escalate_overdue_mistakes(), 1)
        self.assertEqual(Mistake.objects.get(pk=mid).escalation_level, 2)
        Mistake.objects.filter(pk=mid).update(
            sla_due_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(escalate_overdue_mistakes(), 0)   # capped

    def test_resolved_mistakes_never_escalate(self):
        mid = self.log_mistake(self.manager, self.rahul).data["id"]
        Mistake.objects.filter(pk=mid).update(
            status=MistakeStatus.RESOLVED,
            sla_due_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(escalate_overdue_mistakes(), 0)


class TaskIntegrationTests(MistakeBase):
    def test_corrective_task_roundtrip(self):
        mid = self.log_mistake(self.manager, self.rahul).data["id"]
        res = self.client.post(f"/api/mistakes/{mid}/create_task/",
                               {"title": "Audit parts ordering process",
                                "assigned_to": self.rahul.id, "due_days": 1},
                               format="json")
        self.assertEqual(res.status_code, 201)
        task_id = res.data["corrective_task"]
        task = Task.objects.get(pk=task_id)
        self.assertEqual(task.assigned_to, self.rahul)
        self.assertIn("M-", task.description)
        # completing the task writes back into the mistake's history
        self.as_(self.rahul)
        self.client.post(f"/api/tasks/{task_id}/complete/",
                         {"remarks": "process audited", "actual_minutes": 30},
                         format="json")
        m = Mistake.objects.get(pk=mid)
        self.assertTrue(m.events.filter(text__contains="Corrective task").exists())
        self.assertTrue(Notification.objects.filter(
            user=self.manager, type="mistake_update").exists())
        # only one corrective task per mistake
        self.as_(self.manager)
        self.assertEqual(self.client.post(
            f"/api/mistakes/{mid}/create_task/", {}, format="json").status_code, 400)


class ConfigTests(MistakeBase):
    def test_category_admin_only_write_delete_deactivates(self):
        self.as_(self.manager)
        self.assertEqual(self.client.post("/api/mistake-categories/",
                                          {"name": "New Cat"}).status_code, 403)
        self.as_(self.admin)
        res = self.client.post("/api/mistake-categories/", {"name": "Packaging Error"})
        self.assertEqual(res.status_code, 201)
        cat = MistakeCategory.objects.get(name="Packaging Error")
        self.client.delete(f"/api/mistake-categories/{cat.id}/")
        cat.refresh_from_db()
        self.assertFalse(cat.active)

    def test_sla_settings_configurable_by_admin(self):
        self.as_(self.rahul)
        self.assertEqual(self.client.get("/api/mistake-settings/").data["sla_critical_hours"], 4)
        self.assertEqual(self.client.post("/api/mistake-settings/",
                                          {"sla_high_hours": 12}, format="json").status_code, 403)
        self.as_(self.admin)
        res = self.client.post("/api/mistake-settings/", {"sla_high_hours": 12}, format="json")
        self.assertEqual(res.data["sla_high_hours"], 12)
