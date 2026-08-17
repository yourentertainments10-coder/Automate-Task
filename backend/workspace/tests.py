from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from crm.models import Task

from .models import Group, Idea, Link, LinkCollection, Notice


def make(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


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


class GroupTests(Base):
    def test_exec_cannot_create_group_manager_can(self):
        self.as_(self.rahul)
        self.assertEqual(self.client.post("/api/groups/", {"name": "X"}).status_code, 403)
        self.as_(self.manager)
        res = self.client.post("/api/groups/", {"name": "Sales Sprint", "category": "Sales"})
        self.assertEqual(res.status_code, 201)
        g = Group.objects.get()
        self.assertEqual(g.owner, self.manager)
        self.assertTrue(g.members.filter(pk=self.manager.pk).exists())  # auto-member

    def test_membership_visibility(self):
        g1 = Group.objects.create(name="Mine", owner=self.manager)
        g1.members.add(self.rahul)
        Group.objects.create(name="Other", owner=self.manager)
        self.as_(self.rahul)
        names = [g["name"] for g in self.client.get("/api/groups/").data]
        self.assertEqual(names, ["Mine"])
        self.as_(self.admin)  # admin sees all
        self.assertEqual(len(self.client.get("/api/groups/").data), 2)

    def test_only_owner_or_admin_manages_members(self):
        g = Group.objects.create(name="G", owner=self.manager)
        g.members.add(self.rahul)
        self.as_(self.rahul)
        res = self.client.post(f"/api/groups/{g.id}/add_member/", {"user": self.amit.id})
        self.assertEqual(res.status_code, 403)
        self.as_(self.manager)
        res = self.client.post(f"/api/groups/{g.id}/add_member/", {"user": self.amit.id})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(g.members.filter(pk=self.amit.pk).exists())
        self.client.post(f"/api/groups/{g.id}/remove_member/", {"user": self.amit.id})
        self.assertFalse(g.members.filter(pk=self.amit.pk).exists())

    def test_destroy_archives_instead_of_deleting(self):
        g = Group.objects.create(name="G", owner=self.manager)
        self.as_(self.manager)
        self.client.delete(f"/api/groups/{g.id}/")
        g.refresh_from_db()
        self.assertFalse(g.active)

    def test_group_member_sees_group_tasks(self):
        g = Group.objects.create(name="G", owner=self.manager)
        g.members.add(self.rahul)
        Task.objects.create(title="Group work", assigned_to=self.amit,
                            created_by=self.manager, group=g)
        self.as_(self.rahul)  # not assignee, not creator -- but group member
        res = self.client.get("/api/tasks/")
        titles = [t["title"] for t in res.data["results"]]
        self.assertIn("Group work", titles)

    def test_cannot_create_task_in_foreign_group(self):
        g = Group.objects.create(name="G", owner=self.manager)
        self.as_(self.rahul)
        res = self.client.post("/api/tasks/", {"title": "X", "assigned_to": self.rahul.id,
                                               "group": g.id})
        self.assertEqual(res.status_code, 403)

    def test_group_dashboard_counts(self):
        g = Group.objects.create(name="G", owner=self.manager)
        g.members.add(self.rahul)
        now = timezone.now()
        Task.objects.create(title="a", assigned_to=self.rahul, group=g)
        Task.objects.create(title="b", assigned_to=self.rahul, group=g, status="in_progress")
        Task.objects.create(title="c", assigned_to=self.rahul, group=g, status="done")
        Task.objects.create(title="d", assigned_to=self.rahul, group=g,
                            due_at=now - timedelta(hours=1))
        self.as_(self.manager)
        tiles = self.client.get(f"/api/groups/{g.id}/dashboard/").data["tiles"]
        self.assertEqual(tiles, {"total": 4, "pending": 2, "in_progress": 1,
                                 "completed": 1, "overdue": 1, "members": 1})


class NoticeTests(Base):
    def publish(self, **kw):
        defaults = dict(title="N", status="published", author=self.admin)
        defaults.update(kw)
        return Notice.objects.create(**defaults)

    def test_everyone_notice_visible_and_read_flow(self):
        n = self.publish(title="All hands")
        self.as_(self.rahul)
        feed = self.client.get("/api/notices/").data
        self.assertEqual([x["title"] for x in feed], ["All hands"])
        self.assertFalse(feed[0]["read"])
        self.client.post(f"/api/notices/{n.id}/read/")
        feed = self.client.get("/api/notices/?read=true").data
        self.assertEqual(len(feed), 1)
        self.assertEqual(len(self.client.get("/api/notices/?read=false").data), 0)

    def test_targeting_role_department_users_group(self):
        self.publish(title="For execs", audience_type="role",
                     audience_value={"role": "sales_executive"})
        self.publish(title="For accounts dept", audience_type="department",
                     audience_value={"department": "accounts"})
        self.publish(title="For amit only", audience_type="users",
                     audience_value={"users": [self.amit.id]})
        g = Group.objects.create(name="G", owner=self.manager)
        g.members.add(self.rahul)
        self.publish(title="For group", audience_type="group", audience_value={"group": g.id})
        self.as_(self.rahul)
        titles = sorted(x["title"] for x in self.client.get("/api/notices/").data)
        self.assertEqual(titles, ["For execs", "For group"])
        self.as_(self.amit)
        titles = sorted(x["title"] for x in self.client.get("/api/notices/").data)
        self.assertEqual(titles, ["For amit only", "For execs"])

    def test_draft_scheduled_and_expired_are_hidden(self):
        now = timezone.now()
        self.publish(title="Draft", status="draft")
        self.publish(title="Future", publish_at=now + timedelta(days=1))
        self.publish(title="Expired", expire_at=now - timedelta(hours=1))
        self.publish(title="Live")
        self.as_(self.rahul)
        titles = [x["title"] for x in self.client.get("/api/notices/").data]
        self.assertEqual(titles, ["Live"])

    def test_manage_is_admin_only_and_publish_action(self):
        self.as_(self.manager)
        self.assertEqual(self.client.get("/api/notices/?manage=true").status_code, 403)
        self.assertEqual(self.client.post("/api/notices/", {"title": "X"}).status_code, 403)
        self.as_(self.admin)
        res = self.client.post("/api/notices/", {"title": "New policy", "content": "Details"})
        self.assertEqual(res.status_code, 201)
        nid = res.data["id"]
        self.assertEqual(self.client.get("/api/notices/?manage=true").data[0]["status"], "draft")
        res = self.client.post(f"/api/notices/{nid}/publish/")
        self.assertEqual(res.data["status"], "published")
        self.assertIsNotNone(res.data["publish_at"])
        res = self.client.post(f"/api/notices/{nid}/archive/")
        self.assertEqual(res.data["status"], "archived")

    def test_audience_validation(self):
        self.as_(self.admin)
        res = self.client.post("/api/notices/", {"title": "X", "audience_type": "users",
                                                 "audience_value": {}}, format="json")
        self.assertEqual(res.status_code, 400)


class LinkTests(Base):
    def setUp(self):
        super().setUp()
        self.coll = LinkCollection.objects.create(name="Important Tools", created_by=self.admin)

    def test_collection_manage_permission(self):
        self.as_(self.rahul)
        self.assertEqual(self.client.post("/api/link-collections/", {"name": "X"}).status_code, 403)
        self.as_(self.manager)
        self.assertEqual(self.client.post("/api/link-collections/", {"name": "E-books"}).status_code, 201)

    def test_add_link_validates_scheme(self):
        self.as_(self.rahul)
        bad = self.client.post("/api/links/", {"collection": self.coll.id, "title": "X",
                                               "url": "javascript:alert(1)"})
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post("/api/links/", {"collection": self.coll.id, "title": "Drive",
                                              "url": "https://drive.google.com"})
        self.assertEqual(ok.status_code, 201)

    def test_group_link_hidden_from_non_members(self):
        g = Group.objects.create(name="G", owner=self.manager)
        g.members.add(self.rahul)
        Link.objects.create(collection=self.coll, title="Secret", url="https://x.com",
                            group=g, added_by=self.manager)
        Link.objects.create(collection=self.coll, title="Public", url="https://y.com",
                            added_by=self.manager)
        self.as_(self.amit)
        titles = [l["title"] for l in self.client.get("/api/links/").data]
        self.assertEqual(titles, ["Public"])
        self.as_(self.rahul)
        titles = sorted(l["title"] for l in self.client.get("/api/links/").data)
        self.assertEqual(titles, ["Public", "Secret"])

    def test_edit_own_only_and_favorite_toggle(self):
        link = Link.objects.create(collection=self.coll, title="A", url="https://a.com",
                                   added_by=self.rahul)
        self.as_(self.amit)
        self.assertEqual(self.client.patch(f"/api/links/{link.id}/", {"title": "B"}).status_code, 403)
        res = self.client.post(f"/api/links/{link.id}/favorite/")
        self.assertTrue(res.data["favorited"])
        favs = self.client.get("/api/links/?favorites=true").data
        self.assertEqual(len(favs), 1)
        self.client.post(f"/api/links/{link.id}/favorite/")
        self.assertEqual(len(self.client.get("/api/links/?favorites=true").data), 0)
        self.as_(self.rahul)
        self.assertEqual(self.client.patch(f"/api/links/{link.id}/", {"title": "B"}).status_code, 200)


class IdeaTests(Base):
    def test_scopes_my_shared_group(self):
        g = Group.objects.create(name="G", owner=self.manager)
        g.members.add(self.rahul)
        Idea.objects.create(title="Shared idea", author=self.amit)
        Idea.objects.create(title="Group idea", author=self.manager, group=g)
        Idea.objects.create(title="My idea", author=self.rahul)
        self.as_(self.rahul)
        my = [i["title"] for i in self.client.get("/api/ideas/?scope=my").data["results"]]
        self.assertEqual(my, ["My idea"])
        shared = sorted(i["title"] for i in self.client.get("/api/ideas/?scope=shared").data["results"])
        self.assertEqual(shared, ["My idea", "Shared idea"])
        grp = [i["title"] for i in self.client.get("/api/ideas/?scope=group").data["results"]]
        self.assertEqual(grp, ["Group idea"])
        # amit is not in the group -> group idea invisible
        self.as_(self.amit)
        grp = [i["title"] for i in self.client.get("/api/ideas/?scope=group").data["results"]]
        self.assertEqual(grp, [])

    def test_group_idea_requires_membership(self):
        g = Group.objects.create(name="G", owner=self.manager)
        self.as_(self.rahul)
        res = self.client.post("/api/ideas/", {"title": "X", "group": g.id})
        self.assertEqual(res.status_code, 403)

    def test_status_change_needs_review_capability(self):
        idea = Idea.objects.create(title="I", author=self.rahul)
        self.as_(self.rahul)
        self.assertEqual(self.client.patch(f"/api/ideas/{idea.id}/", {"status": "approved"}).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/ideas/{idea.id}/", {"title": "I2"}).status_code, 200)
        self.as_(self.manager)
        res = self.client.patch(f"/api/ideas/{idea.id}/", {"status": "approved"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "approved")

    def test_cannot_edit_others_idea(self):
        idea = Idea.objects.create(title="I", author=self.rahul)
        self.as_(self.amit)
        self.assertEqual(self.client.patch(f"/api/ideas/{idea.id}/", {"title": "hack"}).status_code, 403)

    def test_comments_and_votes(self):
        idea = Idea.objects.create(title="I", author=self.rahul)
        self.as_(self.amit)
        res = self.client.post(f"/api/ideas/{idea.id}/comments/", {"body": "Nice one"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(self.client.get(f"/api/ideas/{idea.id}/comments/").data), 1)
        self.assertEqual(self.client.post(f"/api/ideas/{idea.id}/comments/", {"body": "  "}).status_code, 400)
        res = self.client.post(f"/api/ideas/{idea.id}/vote/")
        self.assertEqual(res.data, {"voted": True, "vote_count": 1})
        res = self.client.post(f"/api/ideas/{idea.id}/vote/")
        self.assertEqual(res.data, {"voted": False, "vote_count": 0})
