"""The one entry point for notifying a user.

notify() ALWAYS creates the in-app notification, then fans out to Gmail and
WhatsApp. Channel senders are inert until configured, and every attempt
(sent / skipped / error) is recorded on the notification row itself.
"""
from .channels import gmail, whatsapp
from .models import Notification


def notify(user, type_: str, title: str, body: str = "", link: str = "",
           wa_template: tuple[str, list] | None = None) -> Notification:
    """wa_template=(template_name, [params]) routes the WhatsApp leg through
    an approved Meta template (deliverable any time); without it the message
    goes as free-form text, which Meta only delivers inside a 24h
    customer-service window."""
    results = []
    results.append(gmail.send_email(user.email, f"[Automation Task] {title}", body or title))
    if wa_template:
        results.append(whatsapp.send_template(user.whatsapp_phone, wa_template[0], wa_template[1]))
    else:
        results.append(whatsapp.send_text(user.whatsapp_phone, f"{title}\n{body}".strip()))
    return Notification.objects.create(
        user=user, type=type_, title=title, body=body, link=link, channels=results,
    )


def notify_lead_assigned(lead, actor=None):
    if not lead.assigned_to:
        return None
    if actor is not None and actor.pk == lead.assigned_to.pk:
        return None  # self-assignment needs no ping
    who = (actor.get_full_name() or actor.username) if actor else "System"
    return notify(
        lead.assigned_to, "lead_assigned",
        f"New lead assigned: {lead.customer_name}",
        f"{lead.requirement or 'No requirement captured yet.'}\n"
        f"Source: {lead.get_source_display()} · Priority: {lead.get_priority_display()} · By: {who}",
        link="/leads",
    )


def notify_status_change(lead, actor, old_status_label):
    if not lead.assigned_to or actor.pk == lead.assigned_to.pk:
        return None
    return notify(
        lead.assigned_to, "status_change",
        f"Lead updated: {lead.customer_name}",
        f"Status changed {old_status_label} -> {lead.get_status_display()} "
        f"by {actor.get_full_name() or actor.username}",
        link="/leads",
    )


def notify_follow_up_due(lead):
    if not lead.assigned_to:
        return None
    return notify(
        lead.assigned_to, "follow_up_due",
        f"Follow-up due: {lead.customer_name}",
        f"{lead.requirement or ''}\nStatus: {lead.get_status_display()} · "
        f"Phone: {lead.phone or '-'}".strip(),
        wa_template=("lead_followup_due", [
            lead.assigned_to.get_full_name() or lead.assigned_to.username,
            lead.customer_name,
            lead.get_status_display(),
            lead.phone or "not on file",
        ]),
        link="/leads",
    )
