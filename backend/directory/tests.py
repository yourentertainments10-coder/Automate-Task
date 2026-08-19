import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User
from crm.models import Task, TaskTemplate
from workspace.models import Group

from .models import DirectoryTemplate, Industry

SAMPLE = [{
    "industry": "E-commerce", "icon": "🛒", "description": "Online sellers.",
    "templates": [
        {"category": "Orders", "name": "Daily order processing", "priority": "high",
         "frequency": "daily", "tags": ["ops"],
         "steps": [
             {"title": "Download orders", "description": "All marketplaces", "offset_days": 0},
             {"title": "Print labels", "offset_days": 1},
         ]},
        {"category": "Returns", "name": "Return handling", "priority": "bogus",
         "frequency": "nonsense",
         "steps": [{"title": "Receive parcel"}]},
        {"category": "Broken", "name": "No steps template", "steps": []},
    ],
}, {
    "industry": "CA Firm", "icon": "📊",
    "templates": [{"category": "GST", "name": "Monthly GST filing",
                   "steps": [{"title": "Collect registers"}]}],
}]


def write_json(data):
    path = Path(tempfile.mkdtemp()) / "pack.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def make(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


class LoaderTests(TestCase):
    def test_json_load_is_idempotent_and_validates(self):
        path = write_json(SAMPLE)
        call_command("load_directory", path)
        self.assertEqual(Industry.objects.count(), 2)
        self.assertEqual(DirectoryTemplate.objects.count(), 3)  # step-less one skipped
        tpl = DirectoryTemplate.objects.get(name="Daily order processing")
        self.assertEqual(tpl.step_count, 2)
        self.assertEqual(tpl.priority, "high")
        # invalid enum values fall back to safe defaults
        bad = DirectoryTemplate.objects.get(name="Return handling")
        self.assertEqual((bad.priority, bad.frequency), ("normal", "one_time"))
        # re-running updates instead of duplicating
        call_command("load_directory", path)
        self.assertEqual(DirectoryTemplate.objects.count(), 3)
        self.assertEqual(Industry.objects.count(), 2)

    def test_csv_load(self):
        csv_path = Path(tempfile.mkdtemp()) / "pack.csv"
        csv_path.write_text(
            "industry,icon,category,template,priority,frequency,tags,step_title,offset_days\n"
            "Photography,📷,Events,Wedding shoot,high,one_time,shoot|delivery,Confirm dates,0\n"
            "Photography,📷,Events,Wedding shoot,high,one_time,shoot|delivery,Backup footage,10\n"
            "Photography,📷,Events,Portfolio update,normal,monthly,,Pick best shots,0\n",
            encoding="utf-8")
        call_command("load_directory", str(csv_path))
        self.assertEqual(Industry.objects.count(), 1)
        self.assertEqual(DirectoryTemplate.objects.count(), 2)
        wedding = DirectoryTemplate.objects.get(name="Wedding shoot")
        self.assertEqual(wedding.step_count, 2)
        self.assertEqual(wedding.tags, ["shoot", "delivery"])

    def test_replace_flag_wipes_first(self):
        call_command("load_directory", write_json(SAMPLE))
        call_command("load_directory", write_json([SAMPLE[1]]), "--replace")
        self.assertEqual(Industry.objects.count(), 1)
        self.assertEqual(Industry.objects.get().name, "CA Firm")

    def test_bundled_starter_pack_loads(self):
        call_command("load_directory")
        self.assertGreaterEqual(Industry.objects.count(), 10)
        self.assertGreaterEqual(DirectoryTemplate.objects.count(), 20)
        for tpl in DirectoryTemplate.objects.all():
            self.assertTrue(tpl.steps, tpl.name)


class BrowseTests(TestCase):
    def setUp(self):
        call_command("load_directory", write_json(SAMPLE))
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.manager = make("meera", Role.SALES_MANAGER)
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)

    def as_(self, user):
        res = self.client.post("/api/auth/login", {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_requires_login(self):
        self.assertEqual(self.client.get("/api/directory/industries/").status_code, 401)

    def test_industries_expose_counts_and_categories(self):
        self.as_(self.rahul)
        rows = self.client.get("/api/directory/industries/").data
        ecom = next(r for r in rows if r["name"] == "E-commerce")
        self.assertEqual(ecom["template_count"], 2)
        self.assertEqual(sorted(ecom["categories"]), ["Orders", "Returns"])
        self.assertEqual(ecom["icon"], "🛒")

    def test_filters_and_search(self):
        self.as_(self.rahul)
        ecom = Industry.objects.get(name="E-commerce")
        rows = self.client.get(f"/api/directory/templates/?industry={ecom.id}").data
        self.assertEqual(len(rows), 2)
        rows = self.client.get("/api/directory/templates/?slug=ca-firm").data
        self.assertEqual(rows[0]["name"], "Monthly GST filing")
        rows = self.client.get("/api/directory/templates/?category=orders").data
        self.assertEqual(len(rows), 1)
        rows = self.client.get("/api/directory/templates/?search=gst").data
        self.assertEqual(len(rows), 1)
        rows = self.client.get("/api/directory/templates/?tag=ops").data
        self.assertEqual(len(rows), 1)

    def test_content_writes_are_admin_only(self):
        self.as_(self.manager)
        ecom = Industry.objects.get(name="E-commerce")
        res = self.client.post("/api/directory/templates/", {
            "industry": ecom.id, "category": "X", "name": "Hand made", "steps": []}, format="json")
        self.assertEqual(res.status_code, 403)
        self.as_(self.admin)
        res = self.client.post("/api/directory/templates/", {
            "industry": ecom.id, "category": "X", "name": "Hand made",
            "steps": [{"title": "Step"}]}, format="json")
        self.assertEqual(res.status_code, 201)


class UseTemplateTests(TestCase):
    def setUp(self):
        call_command("load_directory", write_json(SAMPLE))
        self.client = APIClient()
        self.manager = make("meera", Role.SALES_MANAGER)
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)
        self.amit = make("amit", Role.SALES_EXECUTIVE)
        self.tpl = DirectoryTemplate.objects.get(name="Daily order processing")

    def as_(self, user):
        res = self.client.post("/api/auth/login", {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_add_to_my_templates_needs_capability(self):
        self.as_(self.rahul)
        res = self.client.post(f"/api/directory/templates/{self.tpl.id}/add_to_my_templates/")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(TaskTemplate.objects.count(), 0)

    def test_add_to_my_templates_copies_steps_and_dedupes_names(self):
        self.as_(self.manager)
        res = self.client.post(f"/api/directory/templates/{self.tpl.id}/add_to_my_templates/")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(TaskTemplate.objects.count(), 2)
        first = TaskTemplate.objects.first()
        self.assertEqual(first.category, "Orders")
        self.assertEqual(first.frequency, "daily")
        self.assertEqual(first.created_by, self.manager)
        # second copy must not blow up on the unique name
        res = self.client.post(f"/api/directory/templates/{self.tpl.id}/add_to_my_templates/")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(TaskTemplate.objects.count(), 4)

    def test_create_tasks_for_self_with_offsets(self):
        self.as_(self.rahul)
        res = self.client.post(f"/api/directory/templates/{self.tpl.id}/create_tasks/",
                               {}, format="json")
        self.assertEqual(res.status_code, 201)
        tasks = Task.objects.order_by("id")
        self.assertEqual(tasks.count(), 2)
        self.assertEqual({t.assigned_to for t in tasks}, {self.rahul})
        self.assertEqual(tasks[0].category, "Orders")
        self.assertIsNone(tasks[0].due_at)          # offset 0 -> no due date
        self.assertIsNotNone(tasks[1].due_at)       # offset 1 -> due tomorrow
        self.assertTrue(tasks[0].activities.filter(text__contains="directory template").exists())

    def test_create_tasks_hierarchy_and_notifies(self):
        from notifications.models import Notification
        # Task Engine v2: peer-to-peer allowed, upward blocked
        self.as_(self.rahul)
        res = self.client.post(f"/api/directory/templates/{self.tpl.id}/create_tasks/",
                               {"assigned_to": self.manager.id}, format="json")
        self.assertEqual(res.status_code, 403)          # employee -> manager: no
        res = self.client.post(f"/api/directory/templates/{self.tpl.id}/create_tasks/",
                               {"assigned_to": self.amit.id}, format="json")
        self.assertEqual(res.status_code, 201)          # employee -> employee: yes
        self.assertEqual(Task.objects.filter(assigned_to=self.amit).count(), 2)
        self.assertTrue(Notification.objects.filter(user=self.amit, type="task_assigned").exists())

    def test_create_tasks_into_foreign_group_blocked(self):
        group = Group.objects.create(name="Ops", owner=self.manager)
        self.as_(self.rahul)
        res = self.client.post(f"/api/directory/templates/{self.tpl.id}/create_tasks/",
                               {"group": group.id}, format="json")
        self.assertEqual(res.status_code, 403)
        group.members.add(self.rahul)
        res = self.client.post(f"/api/directory/templates/{self.tpl.id}/create_tasks/",
                               {"group": group.id}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Task.objects.filter(group=group).count(), 2)

    def test_unknown_assignee_rejected(self):
        self.as_(self.manager)
        res = self.client.post(f"/api/directory/templates/{self.tpl.id}/create_tasks/",
                               {"assigned_to": 9999}, format="json")
        self.assertEqual(res.status_code, 400)
