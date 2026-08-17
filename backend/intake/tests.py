import hashlib
import hmac
import json
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, User
from crm.models import AssignmentRule, Lead
from notifications.models import Notification

from .ai import classify
from .models import InboundMessage
from .pipeline import process_message


def make(username, role, department="sales"):
    return User.objects.create_user(username, f"{username}@x.com", "pass@12345",
                                    role=role, department=department)


def wa_payload(msg_id, sender, text, name="Test Customer"):
    return {
        "entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": sender, "profile": {"name": name}}],
            "messages": [{"id": msg_id, "from": sender, "type": "text",
                          "text": {"body": text}}],
        }}]}],
    }


class RulesClassifierTests(TestCase):
    def test_spec_example_brake_pad_tata_407(self):
        # The exact example from the requirements document
        r = classify("Need brake pad and oil filter for Tata 407.", "Suresh")
        self.assertEqual(r["intent"], "purchase")
        self.assertEqual(r["vehicle"], "tata 407")
        names = [i["name"] for i in r["items"]]
        self.assertIn("brake pad", names)
        self.assertIn("oil filter", names)
        self.assertEqual(r["priority"], "normal")
        self.assertEqual(r["department"], "sales")
        self.assertEqual(r["provider"], "rules")

    def test_urgent_support_message(self):
        r = classify("My clutch plate is defective, urgent replacement needed", "")
        self.assertEqual(r["intent"], "support")
        self.assertEqual(r["department"], "support")
        self.assertEqual(r["priority"], "urgent")

    def test_accounts_message(self):
        r = classify("Please share the invoice for last month's payment", "")
        self.assertEqual(r["department"], "accounts")

    def test_spam(self):
        r = classify("OFFER!! click here to win a lottery", "")
        self.assertEqual(r["intent"], "spam")

    def test_quantity_extraction(self):
        r = classify("Need 4 pcs brake pad and 2 oil filter for Tata Ace", "")
        by_name = {i["name"]: i["quantity"] for i in r["items"]}
        self.assertEqual(by_name.get("brake pad"), 4)
        self.assertEqual(by_name.get("oil filter"), 2)


class ClaudeProviderTests(TestCase):
    @mock.patch.dict("os.environ", {"AI_ENABLED": "true", "ANTHROPIC_API_KEY": "sk-ant-test"})
    @mock.patch("intake.ai.requests.post")
    def test_claude_reply_is_used(self, post):
        post.return_value = mock.Mock(status_code=200, json=lambda: {
            "content": [{"type": "text", "text": json.dumps({
                "intent": "purchase", "customer_name": "Suresh Kumar",
                "vehicle": "Tata 407", "items": [{"name": "Brake Pad", "quantity": None}],
                "priority": "normal", "department": "sales", "summary": "Brake pads for Tata 407",
            })}],
        })
        r = classify("Need brake pad for Tata 407", "Suresh")
        self.assertEqual(r["provider"], "claude")
        self.assertEqual(r["customer_name"], "Suresh Kumar")
        body = post.call_args.kwargs["json"]
        self.assertIn("classify", body["system"].lower())

    @mock.patch.dict("os.environ", {"AI_ENABLED": "true", "ANTHROPIC_API_KEY": "sk-ant-test"})
    @mock.patch("intake.ai.requests.post")
    def test_claude_failure_falls_back_to_rules(self, post):
        post.return_value = mock.Mock(status_code=500, text="boom")
        r = classify("Need brake pad for Tata 407", "")
        self.assertEqual(r["provider"], "rules")
        self.assertEqual(r["intent"], "purchase")


class PipelineTests(TestCase):
    def setUp(self):
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)
        self.amit = make("amit", Role.SALES_EXECUTIVE)
        AssignmentRule.objects.create(department="sales", strategy="round_robin",
                                      member_ids=[self.rahul.pk, self.amit.pk])

    def inbound(self, body, sender="919876543210", channel="whatsapp", **kw):
        n = InboundMessage.objects.count()
        return InboundMessage.objects.create(
            channel=channel, external_id=f"t-{n}", sender=sender,
            sender_name="Suresh", body=body, **kw)

    def test_new_whatsapp_message_creates_assigned_lead(self):
        msg = process_message(self.inbound("Need brake pad and oil filter for Tata 407."))
        self.assertEqual(msg.status, "processed")
        lead = msg.lead
        self.assertEqual(lead.source, "whatsapp")
        self.assertEqual(lead.phone, "919876543210")
        self.assertEqual(lead.assigned_to, self.rahul)       # round-robin #1
        self.assertIn("brake pad", lead.requirement)
        self.assertIn("tata 407", lead.requirement)
        self.assertEqual(lead.ai_meta["classification"]["intent"], "purchase")
        self.assertTrue(Notification.objects.filter(user=self.rahul, type="lead_assigned").exists())

    def test_followup_message_updates_existing_lead(self):
        first = process_message(self.inbound("Need brake pad for Tata 407"))
        lead = first.lead
        second = process_message(self.inbound("Also need wiper blades please"))
        self.assertEqual(second.lead, lead)                   # matched by phone
        self.assertEqual(Lead.objects.count(), 1)             # no duplicate lead
        events = lead.events.filter(type="wa_in")
        self.assertEqual(events.count(), 2)
        self.assertTrue(Notification.objects.filter(user=self.rahul, type="customer_message").exists())

    def test_gmail_message_matches_by_email(self):
        Lead.objects.create(customer_name="Sunita", email="sunita@x.com",
                            department="sales", assigned_to=self.amit)
        msg = process_message(self.inbound("Any update on my quotation?",
                                           sender="sunita@x.com", channel="gmail",
                                           subject="Quotation follow-up"))
        self.assertEqual(msg.lead.customer_name, "Sunita")
        self.assertEqual(msg.lead.events.filter(type="email_in").count(), 1)

    def test_spam_is_ignored_no_lead(self):
        msg = process_message(self.inbound("OFFER!! click here to win a lottery"))
        self.assertEqual(msg.status, "ignored")
        self.assertIsNone(msg.lead)
        self.assertEqual(Lead.objects.count(), 0)


@override_settings(ALLOWED_HOSTS=["testserver"])
class WebhookTests(TestCase):
    def setUp(self):
        self.rahul = make("rahul", Role.SALES_EXECUTIVE)
        AssignmentRule.objects.create(department="sales", member_ids=[self.rahul.pk])

    def test_get_verify_handshake(self):
        with mock.patch.dict("os.environ", {"WHATSAPP_WEBHOOK_VERIFY_TOKEN": "tok123"}):
            res = self.client.get("/api/webhooks/whatsapp", {
                "hub.mode": "subscribe", "hub.verify_token": "tok123", "hub.challenge": "42",
            })
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.content, b"42")
            res = self.client.get("/api/webhooks/whatsapp", {
                "hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42",
            })
            self.assertEqual(res.status_code, 403)

    def test_post_creates_lead_end_to_end(self):
        payload = wa_payload("wamid.1", "919876543210", "Need brake pad and oil filter for Tata 407.")
        res = self.client.post("/api/webhooks/whatsapp", json.dumps(payload),
                               content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["ingested"], 1)
        lead = Lead.objects.get()
        self.assertEqual(lead.assigned_to, self.rahul)
        self.assertEqual(lead.source, "whatsapp")

    def test_duplicate_delivery_is_idempotent(self):
        payload = wa_payload("wamid.dup", "919876543210", "Need brake pad")
        for _ in range(2):
            self.client.post("/api/webhooks/whatsapp", json.dumps(payload),
                             content_type="application/json")
        self.assertEqual(InboundMessage.objects.count(), 1)
        self.assertEqual(Lead.objects.count(), 1)

    def test_bad_signature_rejected_when_secret_set(self):
        payload = json.dumps(wa_payload("wamid.sig", "919876543210", "hi"))
        with mock.patch.dict("os.environ", {"WHATSAPP_APP_SECRET": "shh"}):
            res = self.client.post("/api/webhooks/whatsapp", payload,
                                   content_type="application/json",
                                   headers={"X-Hub-Signature-256": "sha256=wrong"})
            self.assertEqual(res.status_code, 403)
            good = hmac.new(b"shh", payload.encode(), hashlib.sha256).hexdigest()
            res = self.client.post("/api/webhooks/whatsapp", payload,
                                   content_type="application/json",
                                   headers={"X-Hub-Signature-256": f"sha256={good}"})
            self.assertEqual(res.status_code, 200)


class IntakeApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make("boss", Role.ADMIN, "management")
        self.exec_ = make("neha", Role.SALES_EXECUTIVE)

    def as_(self, username):
        res = self.client.post("/api/auth/login", {"username": username, "password": "pass@12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_intake_list_requires_capability(self):
        self.as_("neha")
        self.assertEqual(self.client.get("/api/intake/").status_code, 403)
        self.as_("boss")
        self.assertEqual(self.client.get("/api/intake/").status_code, 200)

    def test_simulate_runs_pipeline(self):
        self.as_("boss")
        res = self.client.post("/api/intake/simulate/", {
            "channel": "whatsapp", "sender": "919000000001",
            "sender_name": "Demo", "body": "Need clutch plate for Ashok Leyland Dost",
        })
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["status"], "processed")
        self.assertIsNotNone(res.data["lead"])
        self.assertEqual(res.data["ai_result"]["vehicle"], "ashok leyland dost")

    def test_simulate_admin_only(self):
        self.as_("neha")
        res = self.client.post("/api/intake/simulate/", {
            "channel": "whatsapp", "sender": "1", "body": "x",
        })
        self.assertEqual(res.status_code, 403)
