from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User

from notifications.models import Notification

from .models import Holiday, Task, TaskCategory, TaskTemplate


def make(username, role, department="sales", **kw):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department, **kw)


class Base(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.manager = make("meera", Role.SALES_MANAGER)
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)
        self.amit = make("amit", Role.SALES_EXECUTIVE)

    def as_(self, user):
        res = self.client.post("/api/auth/login", {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")


class ScopeTabTests(Base):
    def setUp(self):
        super().setUp()
        self.t_my = Task.objects.create(title="Mine", assigned_to=self.rahul, created_by=self.manager)
        self.t_deleg = Task.objects.create(title="Delegated", assigned_to=self.amit, created_by=self.manager)
        self.t_self = Task.objects.create(title="Self", assigned_to=self.manager, created_by=self.manager)

    def titles(self, url):
        res = self.client.get(url)
        rows = res.data["results"] if "results" in res.data else res.data
        return sorted(t["title"] for t in rows)

    def test_scope_my(self):
        self.as_(self.manager)
        self.assertEqual(self.titles("/api/tasks/?scope=my"), ["Self"])

    def test_scope_delegated_excludes_self_assigned(self):
        self.as_(self.manager)
        self.assertEqual(self.titles("/api/tasks/?scope=delegated"), ["Delegated", "Mine"])

    def test_scope_subscribed(self):
        self.t_my.subscribers.add(self.amit)
        self.as_(self.amit)
        self.assertEqual(self.titles("/api/tasks/?scope=subscribed"), ["Mine"])

    def test_creator_auto_subscribes_via_api(self):
        self.as_(self.manager)
        res = self.client.post("/api/tasks/", {"due_at": (timezone.now() + timedelta(days=1)).isoformat(), "title": "New", "assigned_to": self.rahul.id,
                                               "effort_minutes": 30})
        task = Task.objects.get(pk=res.data["id"])
        self.assertTrue(task.subscribers.filter(pk=self.manager.pk).exists())

    def test_subscribe_unsubscribe(self):
        self.as_(self.amit)
        # amit can see t_my? No: not assigned/created. Use own task
        t = Task.objects.create(title="A-task", assigned_to=self.amit)
        self.client.post(f"/api/tasks/{t.id}/subscribe/")
        self.assertTrue(t.subscribers.filter(pk=self.amit.pk).exists())
        self.client.post(f"/api/tasks/{t.id}/unsubscribe/")
        self.assertFalse(t.subscribers.filter(pk=self.amit.pk).exists())


class TaskDashboardTests(Base):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        # rahul's tasks: 1 overdue-open, 1 pending future, 1 in-progress,
        # 1 completed in time, 1 completed late (its due date was yesterday)
        Task.objects.create(title="od", assigned_to=self.rahul, category="Calls",
                            due_at=now - timedelta(minutes=5))
        Task.objects.create(title="pend", assigned_to=self.rahul, category="Calls",
                            due_at=now + timedelta(days=1))
        Task.objects.create(title="prog", assigned_to=self.rahul, category="Quotes",
                            status="in_progress", due_at=now + timedelta(days=1))
        Task.objects.create(title="done-ok", assigned_to=self.rahul, category="Quotes",
                            status="done", due_at=now + timedelta(minutes=30), completed_at=now)
        Task.objects.create(title="done-late", assigned_to=self.rahul, category="Quotes",
                            status="done", due_at=now - timedelta(days=1), completed_at=now)

    def test_tiles_math(self):
        self.as_(self.rahul)
        data = self.client.get("/api/tasks/dashboard/?range=all&scope=my").data
        self.assertEqual(data["tiles"], {
            "overdue": 1, "pending": 2, "in_progress": 1,
            "completed": 2, "in_time": 1, "delayed": 1, "total": 5,
        })

    def test_category_table(self):
        self.as_(self.rahul)
        cats = self.client.get("/api/tasks/dashboard/?range=all&scope=my").data["categories"]
        calls = next(c for c in cats if c["category"] == "Calls")
        self.assertEqual((calls["total"], calls["overdue"], calls["pending"]), (2, 1, 2))
        quotes = next(c for c in cats if c["category"] == "Quotes")
        self.assertEqual((quotes["total"], quotes["completed"], quotes["delayed"]), (3, 2, 1))

    def test_range_today_excludes_next_week(self):
        Task.objects.create(title="far", assigned_to=self.rahul,
                            due_at=timezone.now() + timedelta(days=30))
        self.as_(self.rahul)
        data = self.client.get("/api/tasks/dashboard/?range=today&scope=my").data
        self.assertEqual(data["tiles"]["total"], 2)  # od + done-ok anchor today; done-late was due yesterday

    def test_group_scope_needs_capability(self):
        self.as_(self.rahul)
        self.assertEqual(self.client.get("/api/tasks/dashboard/?scope=group").status_code, 403)
        self.as_(self.manager)
        self.assertEqual(self.client.get("/api/tasks/dashboard/?scope=group").status_code, 200)


class RecurrenceTests(Base):
    def test_completing_weekly_task_spawns_next(self):
        due = timezone.now() + timedelta(hours=2)
        t = Task.objects.create(title="Weekly report", assigned_to=self.rahul,
                                frequency="weekly", due_at=due)
        self.as_(self.rahul)
        self.client.post(f"/api/tasks/{t.id}/complete/",
                         {"remarks": "sent", "actual_minutes": 30}, format="json")
        nxt = Task.objects.exclude(pk=t.pk).get(title="Weekly report")
        self.assertEqual(nxt.status, "open")
        self.assertEqual((nxt.due_at - due).days, 7)

    def test_one_time_task_does_not_recur(self):
        t = Task.objects.create(title="Once", assigned_to=self.rahul,
                                due_at=timezone.now())
        self.as_(self.rahul)
        self.client.post(f"/api/tasks/{t.id}/complete/",
                         {"remarks": "done", "actual_minutes": 5}, format="json")
        self.assertEqual(Task.objects.filter(title="Once").count(), 1)


class TemplateHolidayTests(Base):
    def test_templates_read_all_write_assigners_only(self):
        self.as_(self.rahul)
        res = self.client.post("/api/task-templates/", {"name": "T", "title": "X"})
        self.assertEqual(res.status_code, 403)
        self.as_(self.manager)
        res = self.client.post("/api/task-templates/", {
            "name": "Daily call sheet", "category": "Calls",
            "title": "Prepare call sheet", "priority": "high", "frequency": "daily",
        })
        self.assertEqual(res.status_code, 201)
        self.as_(self.rahul)
        res = self.client.get("/api/task-templates/")
        self.assertEqual(len(res.data), 1)

    def test_holidays_read_all_write_admin_only(self):
        Holiday.objects.create(name="Diwali", date="2026-11-08")
        self.as_(self.rahul)
        self.assertEqual(len(self.client.get("/api/holidays/").data), 1)
        self.assertEqual(self.client.post("/api/holidays/", {"name": "X", "date": "2026-12-25"}).status_code, 403)
        self.as_(self.admin)
        self.assertEqual(self.client.post("/api/holidays/", {"name": "Christmas", "date": "2026-12-25"}).status_code, 201)

    def test_activities_feed_scoped(self):
        self.as_(self.manager)
        res = self.client.post("/api/tasks/", {"due_at": (timezone.now() + timedelta(days=1)).isoformat(), "title": "Audit me", "assigned_to": self.rahul.id,
                                               "effort_minutes": 30})
        self.as_(self.rahul)
        acts = self.client.get("/api/task-activities/").data
        rows = acts["results"] if "results" in acts else acts
        self.assertTrue(any("Created and assigned" in a["text"] for a in rows))
        # amit sees nothing (not his task)
        self.as_(self.amit)
        acts = self.client.get("/api/task-activities/").data
        rows = acts["results"] if "results" in acts else acts
        self.assertEqual(len(rows), 0)


class TeamDirectoryTests(Base):
    """My Team scoping: admin = everyone, manager = direct reports only,
    employee = own department."""

    def test_admin_sees_whole_company(self):
        self.as_(self.admin)
        self.assertEqual(len(self.client.get("/api/team/").data), 4)

    def test_manager_sees_only_direct_reports(self):
        self.rahul.reporting_manager = self.manager
        self.rahul.save()
        self.as_(self.manager)
        rows = self.client.get("/api/team/").data
        self.assertEqual([r["username"] for r in rows], ["rahul"])
        self.assertEqual(rows[0]["reports_to"], "meera")
        # amit reports to nobody -> not in meera's team even though same dept
        self.assertNotIn("amit", [r["username"] for r in rows])

    def test_manager_with_no_reports_sees_empty_list(self):
        self.as_(self.manager)
        self.assertEqual(self.client.get("/api/team/").data, [])

    def test_employee_sees_own_department_only(self):
        self.as_(self.rahul)   # sales executive
        names = sorted(r["username"] for r in self.client.get("/api/team/").data)
        self.assertEqual(names, ["amit", "meera", "rahul"])   # sales dept, not admin (management)

    def test_directory_hides_deactivated(self):
        self.amit.is_active = False
        self.amit.save()
        self.as_(self.rahul)
        names = [r["username"] for r in self.client.get("/api/team/").data]
        self.assertNotIn("amit", names)


class CategoryRequestTests(Base):
    """An employee cannot add a category outright — they request it and a
    manager approves. Managers/admin still add straight away."""

    def test_employee_request_needs_approval(self):
        self.rahul.reporting_manager = self.manager
        self.rahul.save(update_fields=["reporting_manager"])
        self.as_(self.rahul)
        res = self.client.post("/api/task-categories/",
                               {"name": "Stock audit", "department": "sales"},
                               format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(res.data["pending"])
        # it must NOT show up in the dropdown yet
        names = [c["name"] for c in self.client.get("/api/task-categories/").data]
        self.assertNotIn("Stock audit", names)
        # the manager was told, and sees it in their pending list
        self.assertTrue(Notification.objects.filter(
            user=self.manager, type="category_request").exists())
        self.as_(self.manager)
        pend = self.client.get("/api/task-categories/?pending=true").data
        self.assertEqual([c["name"] for c in pend], ["Stock audit"])

        cid = pend[0]["id"]
        self.assertEqual(self.client.post(
            f"/api/task-categories/{cid}/approve/").status_code, 200)
        names = [c["name"] for c in self.client.get("/api/task-categories/").data]
        self.assertIn("Stock audit", names)
        self.assertTrue(Notification.objects.filter(
            user=self.rahul, type="category_request",
            title__icontains="approved").exists())

    def test_manager_adds_straight_away(self):
        self.as_(self.manager)
        res = self.client.post("/api/task-categories/",
                               {"name": "Site visit", "department": "sales"},
                               format="json")
        self.assertEqual(res.status_code, 201)
        self.assertFalse(res.data["pending"])
        self.assertIn("Site visit",
                      [c["name"] for c in self.client.get("/api/task-categories/").data])

    def test_employee_cannot_see_or_approve_requests(self):
        self.as_(self.rahul)
        self.client.post("/api/task-categories/", {"name": "Ad hoc"}, format="json")
        self.assertEqual(self.client.get("/api/task-categories/?pending=true").data, [])
        cid = TaskCategory.objects.get(name="Ad hoc").id
        self.assertEqual(self.client.post(
            f"/api/task-categories/{cid}/approve/").status_code, 403)

    def test_rejection_tells_the_requester(self):
        self.rahul.reporting_manager = self.manager
        self.rahul.save(update_fields=["reporting_manager"])
        self.as_(self.rahul)
        self.client.post("/api/task-categories/", {"name": "Random"}, format="json")
        cid = TaskCategory.objects.get(name="Random").id
        self.as_(self.manager)
        self.assertEqual(self.client.post(f"/api/task-categories/{cid}/reject/",
                                          {"remarks": "Use 'Calls' instead"},
                                          format="json").status_code, 200)
        self.assertFalse(TaskCategory.objects.filter(name="Random").exists())
        note = Notification.objects.get(user=self.rahul, type="category_request")
        self.assertIn("not added", note.title)
        self.assertIn("Use 'Calls' instead", note.body)
