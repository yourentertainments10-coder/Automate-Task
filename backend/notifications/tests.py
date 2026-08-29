import os
from unittest import mock

from django.test import TestCase
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
