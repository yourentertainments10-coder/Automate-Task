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


class WhatsAppDeliveryTests(ChannelsDisabledMixin, TestCase):
    """"The system says it was sent" used to be the only answer available,
    because Meta's delivery callback was thrown away. Now a message is
    followed from accepted to delivered, read, or failed-and-why."""

    WEBHOOK = "/api/webhooks/whatsapp"

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.who = make("wa.user", Role.SALES_EXECUTIVE, department="sales",
                        whatsapp_phone="7004130460")

    def sent(self, wamid="wamid.TEST1"):
        from notifications.delivery import WhatsAppDelivery
        return WhatsAppDelivery.objects.create(
            wamid=wamid, user=self.who, phone=self.who.whatsapp_phone,
            template="new_task_assigne", status="accepted")

    def callback(self, wamid, status, errors=None):
        body = {"entry": [{"changes": [{"value": {"statuses": [
            {"id": wamid, "status": status, "recipient_id": "917004130460",
             **({"errors": errors} if errors else {})}]}}]}]}
        return self.client.post(self.WEBHOOK, body, format="json")

    def test_a_send_is_recorded_with_metas_id(self):
        from unittest import mock
        from notifications.delivery import WhatsAppDelivery
        from notifications.service import notify
        fake = {"channel": "whatsapp", "status": "sent", "detail": "",
                "wamid": "wamid.ABC"}
        with mock.patch("notifications.channels.whatsapp.send_template", return_value=fake), \
             mock.patch("notifications.channels.gmail.send_email",
                        return_value={"channel": "gmail", "status": "skipped"}):
            notify(self.who, "task_assigned", "T-00136", wa_template=("new_task_assigne", []))
        row = WhatsAppDelivery.objects.get(wamid="wamid.ABC")
        self.assertEqual(row.user, self.who)
        self.assertEqual(row.status, "accepted")
        self.assertEqual(row.template, "new_task_assigne")

    def test_delivered_is_written_down(self):
        row = self.sent()
        self.assertEqual(self.callback(row.wamid, "delivered").status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, "delivered")

    def test_read_is_written_down(self):
        row = self.sent()
        self.callback(row.wamid, "read")
        row.refresh_from_db()
        self.assertEqual(row.status, "read")

    def test_a_failure_records_why(self):
        """The answer that was missing: it did not arrive, and here is why."""
        row = self.sent()
        self.callback(row.wamid, "failed", errors=[{
            "code": 131026, "title": "Message undeliverable",
            "message": "Receiver is incapable of receiving this message"}])
        row.refresh_from_db()
        self.assertEqual(row.status, "failed")
        self.assertIn("131026", row.detail)
        self.assertIn("undeliverable", row.detail.lower())

    def test_a_late_callback_cannot_walk_it_backwards(self):
        """Meta may deliver 'sent' after 'read'; the message stays read."""
        row = self.sent()
        self.callback(row.wamid, "read")
        self.callback(row.wamid, "sent")
        row.refresh_from_db()
        self.assertEqual(row.status, "read")

    def test_a_failure_always_wins_even_if_late(self):
        row = self.sent()
        self.callback(row.wamid, "delivered")
        self.callback(row.wamid, "failed", errors=[{"code": 131047, "title": "Re-engagement"}])
        row.refresh_from_db()
        self.assertEqual(row.status, "failed")

    def test_an_unknown_id_is_ignored_quietly(self):
        """Messages sent before this table existed must not error the webhook —
        Meta retries a non-200 for days."""
        self.assertEqual(self.callback("wamid.NEVER_SEEN", "delivered").status_code, 200)

    def test_a_malformed_status_does_not_break_the_webhook(self):
        body = {"entry": [{"changes": [{"value": {"statuses": [{"nonsense": True}]}}]}]}
        self.assertEqual(self.client.post(self.WEBHOOK, body, format="json").status_code, 200)

    def test_incoming_messages_still_work_alongside_statuses(self):
        body = {"entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": "919999999999", "profile": {"name": "Ravi"}}],
            "messages": [{"id": "wamid.IN1", "from": "919999999999",
                          "type": "text", "text": {"body": "hello"}}],
            "statuses": [{"id": "wamid.TEST1", "status": "delivered"}],
        }}]}]}
        self.assertEqual(self.client.post(self.WEBHOOK, body, format="json").status_code, 200)
