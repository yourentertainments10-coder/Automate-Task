"""The intake pipeline every inbound message flows through, regardless of
channel:

    InboundMessage -> classify (Claude or rules) -> match existing open lead
    (by phone/email) -> update it, or create a new lead -> auto-assign
    (department rule) -> notify -- exactly the flow in the requirements.
"""
import logging

from django.db.models import Q
from django.utils import timezone

from crm.assignment import auto_assign
from crm.models import EventType, Lead, LeadEvent, OPEN_STATUSES
from notifications.service import notify

from .ai import classify
from .models import InboundMessage

log = logging.getLogger(__name__)

CHANNEL_EVENT = {"whatsapp": EventType.WA_IN, "gmail": EventType.EMAIL_IN}
CHANNEL_SOURCE = {"whatsapp": "whatsapp", "gmail": "gmail"}


def process_message(msg: InboundMessage) -> InboundMessage:
    try:
        result = classify(f"{msg.subject}\n{msg.body}".strip(), msg.sender_name)
        msg.ai_result = result

        if result["intent"] == "spam":
            msg.status = InboundMessage.Status.IGNORED
            msg.processed_at = timezone.now()
            msg.save()
            return msg

        lead = _find_open_lead(msg)
        if lead:
            _append_to_lead(lead, msg, result)
        else:
            lead = _create_lead(msg, result)

        msg.lead = lead
        msg.status = InboundMessage.Status.PROCESSED
        msg.processed_at = timezone.now()
        msg.save()
    except Exception as exc:  # noqa: BLE001 -- a poison message must never kill the webhook
        log.exception("intake pipeline failed for message %s", msg.pk)
        msg.status = InboundMessage.Status.FAILED
        msg.error = str(exc)[:1000]
        msg.processed_at = timezone.now()
        msg.save()
    return msg


def _find_open_lead(msg: InboundMessage) -> Lead | None:
    if msg.channel == InboundMessage.Channel.WHATSAPP:
        cond = Q(phone__icontains=msg.sender[-10:]) if len(msg.sender) >= 10 else Q(phone=msg.sender)
    else:
        cond = Q(email__iexact=msg.sender)
    return (
        Lead.objects.filter(cond, status__in=OPEN_STATUSES)
        .order_by("-updated_at")
        .first()
    )


def _append_to_lead(lead: Lead, msg: InboundMessage, result: dict):
    LeadEvent.objects.create(
        lead=lead, type=CHANNEL_EVENT[msg.channel],
        body=(f"{msg.subject}: " if msg.subject else "") + msg.body[:1000],
        payload={"inbound_id": msg.pk, "ai": result},
    )
    lead.ai_meta = {**lead.ai_meta, "last_classification": result}
    if not lead.requirement and result["summary"]:
        lead.requirement = result["summary"]
    lead.save(update_fields=["ai_meta", "requirement", "updated_at"])
    if lead.assigned_to:
        channel_label = "WhatsApp" if msg.channel == "whatsapp" else "email"
        notify(
            lead.assigned_to, "customer_message",
            f"New {channel_label} message: {lead.customer_name}",
            msg.body[:300], link="/leads",
        )


def _create_lead(msg: InboundMessage, result: dict) -> Lead:
    name = result["customer_name"] or msg.sender_name or msg.sender
    requirement = result["summary"] or msg.body[:500]
    if result["items"]:
        parts = ", ".join(
            (f"{i['quantity']}x {i['name']}" if i["quantity"] else i["name"]) for i in result["items"]
        )
        requirement = f"{parts}" + (f" for {result['vehicle']}" if result["vehicle"] else "")
    lead = Lead.objects.create(
        customer_name=name[:200],
        phone=msg.sender if msg.channel == InboundMessage.Channel.WHATSAPP else "",
        email=msg.sender if msg.channel == InboundMessage.Channel.GMAIL else "",
        requirement=requirement,
        source=CHANNEL_SOURCE[msg.channel],
        department=result["department"],
        priority=result["priority"],
        ai_meta={"classification": result},
    )
    LeadEvent.objects.create(
        lead=lead, type=EventType.CREATED,
        body=f"Lead created from {lead.get_source_display()} ({result['provider']} classification)",
        payload={"inbound_id": msg.pk},
    )
    LeadEvent.objects.create(
        lead=lead, type=CHANNEL_EVENT[msg.channel],
        body=(f"{msg.subject}: " if msg.subject else "") + msg.body[:1000],
        payload={"inbound_id": msg.pk, "ai": result},
    )
    auto_assign(lead)  # department rule; notifies the assignee
    return lead
