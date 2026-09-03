import os
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User

from .models import Notification
from .service import notify


def make(username, role, **kw):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345", role=role, **kw)


class ChannelsDisabledMixin:
    """Real WhatsApp/Gmail credentials may be present in .env — tests must
    never send actual messages, so both channels are forced off."""
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"WHATSAPP_ENABLED": "false", "GMAIL_ENABLED": "false"})
        patcher.start()
        self.addCleanup(patcher.stop)


class NotifyServiceTests(ChannelsDisabledMixin, TestCase):
    def test_notify_creates_inapp_and_records_skipped_channels(self):
        u = make("neha", Role.SALES_EXECUTIVE, whatsapp_phone="919800000001")
        n = notify(u, "test", "Hello", "Body here")
        self.assertEqual(Notification.objects.count(), 1)
        channels = {c["channel"]: c["status"] for c in n.channels}
        # Neither Gmail nor WhatsApp is configured in this environment:
        self.assertEqual(channels, {"gmail": "skipped", "whatsapp": "skipped"})

    def test_whatsapp_skip_reason_without_phone(self):
        u = make("nophone", Role.DEVELOPER)
        n = notify(u, "test", "Hi")
        wa = next(c for c in n.channels if c["channel"] == "whatsapp")
        self.assertIn("no whatsapp number", wa["detail"])


class NotificationApiTests(ChannelsDisabledMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.a = make("asha", Role.SALES_EXECUTIVE)
        self.b = make("bala", Role.SALES_EXECUTIVE)
        notify(self.a, "t1", "For Asha 1")
        notify(self.a, "t2", "For Asha 2")
        notify(self.b, "t3", "For Bala")

    def as_(self, user):
        res = self.client.post("/api/auth/login", {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_own_feed_only(self):
        self.as_(self.a)
        res = self.client.get("/api/notifications/")
        titles = [n["title"] for n in res.data["results"]]
        self.assertEqual(sorted(titles), ["For Asha 1", "For Asha 2"])

    def test_unread_count_read_and_read_all(self):
        self.as_(self.a)
        self.assertEqual(self.client.get("/api/notifications/unread_count/").data["count"], 2)
        first = self.client.get("/api/notifications/").data["results"][0]
        self.client.post(f"/api/notifications/{first['id']}/read/")
        self.assertEqual(self.client.get("/api/notifications/unread_count/").data["count"], 1)
        self.client.post("/api/notifications/read_all/")
        self.assertEqual(self.client.get("/api/notifications/unread_count/").data["count"], 0)

    def test_cannot_read_someone_elses_notification(self):
        self.as_(self.b)
        other = Notification.objects.filter(user=self.a).first()
        self.assertEqual(self.client.post(f"/api/notifications/{other.id}/read/").status_code, 404)


class ClearNotificationsTests(ChannelsDisabledMixin, TestCase):
    """People asked to be able to empty their own list for good. The rows are
    deleted from the database, and one person can never touch another's."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.emp = make("clear.emp", Role.SALES_EXECUTIVE, department="sales")
        self.other = make("clear.other", Role.SALES_EXECUTIVE, department="sales")
        for i in range(3):
            n = Notification.objects.create(user=self.emp, type="test", title=f"read {i}")
            Notification.objects.filter(pk=n.pk).update(read_at=timezone.now())
        for i in range(2):
            Notification.objects.create(user=self.emp, type="test", title=f"unread {i}")
        Notification.objects.create(user=self.other, type="test", title="not yours")

    def as_(self, user):
        res = self.client.post("/api/auth/login",
                               {"username": user.username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_clear_read_leaves_the_unread_ones(self):
        self.as_(self.emp)
        res = self.client.post("/api/notifications/clear/?only=read")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["deleted"], 3)
        left = Notification.objects.filter(user=self.emp)
        self.assertEqual(left.count(), 2)
        self.assertTrue(all(n.read_at is None for n in left))

    def test_clear_all_empties_the_list(self):
        self.as_(self.emp)
        res = self.client.post("/api/notifications/clear/")
        self.assertEqual(res.data["deleted"], 5)
        self.assertEqual(Notification.objects.filter(user=self.emp).count(), 0)

    def test_clearing_never_touches_somebody_elses(self):
        self.as_(self.emp)
        self.client.post("/api/notifications/clear/")
        self.assertEqual(Notification.objects.filter(user=self.other).count(), 1)

    def test_rows_are_really_gone_not_hidden(self):
        self.as_(self.emp)
        self.client.post("/api/notifications/clear/")
        # no soft-delete flag anywhere -- the query is unfiltered on purpose
        self.assertFalse(Notification.objects.filter(user=self.emp).exists())

    def test_one_notification_can_be_deleted_on_its_own(self):
        self.as_(self.emp)
        n = Notification.objects.filter(user=self.emp).first()
        self.assertEqual(self.client.delete(f"/api/notifications/{n.id}/").status_code, 204)
        self.assertFalse(Notification.objects.filter(pk=n.pk).exists())

    def test_you_cannot_delete_somebody_elses(self):
        self.as_(self.emp)
        theirs = Notification.objects.get(user=self.other)
        self.assertEqual(self.client.delete(f"/api/notifications/{theirs.id}/").status_code, 404)
        self.assertTrue(Notification.objects.filter(pk=theirs.pk).exists())

    def test_an_employee_may_clear_their_own_list(self):
        """Everyone gets this, not just admins -- everyone's list fills up."""
        self.as_(self.emp)
        self.assertEqual(self.client.post("/api/notifications/clear/").status_code, 200)
