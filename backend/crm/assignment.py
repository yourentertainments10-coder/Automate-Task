"""Automatic lead assignment.

One rule per department. `member_ids` is an ORDERED list -- round-robin
walks it in order (Lead 1 -> Rahul, 2 -> Amit, 3 -> Priya, 4 -> Rahul...),
skipping users who are deactivated or missing. `fixed` always picks the
first available member.
"""
from accounts.models import User
from notifications.service import notify_lead_assigned

from .models import AssignmentRule, EventType, Lead, LeadEvent


def auto_assign(lead: Lead, actor=None) -> User | None:
    """Assign an unassigned lead per its department's rule. Returns the
    chosen user (already saved + event logged + notified) or None."""
    if lead.assigned_to_id:
        return lead.assigned_to
    rule = AssignmentRule.objects.filter(department=lead.department, active=True).first()
    if not rule or not rule.member_ids:
        return None

    users = {u.pk: u for u in User.objects.filter(pk__in=rule.member_ids, is_active=True)}
    members = [users[pk] for pk in rule.member_ids if pk in users]
    if not members:
        return None

    if rule.strategy == AssignmentRule.Strategy.ROUND_ROBIN:
        chosen = members[rule.rr_index % len(members)]
        rule.rr_index = (rule.rr_index + 1) % len(members)
        rule.save(update_fields=["rr_index"])
    else:  # fixed
        chosen = members[0]

    lead.assigned_to = chosen
    lead.save(update_fields=["assigned_to", "updated_at"])
    LeadEvent.objects.create(
        lead=lead, type=EventType.ASSIGNMENT, actor=actor,
        body=f"Auto-assigned to {chosen.get_full_name() or chosen.username} "
             f"({rule.get_strategy_display()})",
        payload={"assigned_to": chosen.pk, "auto": True},
    )
    notify_lead_assigned(lead, actor=None)  # actor=None => assignee always pinged
    return chosen
