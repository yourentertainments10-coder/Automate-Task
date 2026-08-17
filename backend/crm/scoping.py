"""Which leads a user can SEE and EDIT, derived from the role capability
matrix in accounts.permissions. Kept in one file so the answer to "why can
Anita see this lead?" is always three lines away.
"""
from django.db.models import Q

from accounts.permissions import has_capability

from .models import Lead, LeadStatus, Task


def visible_leads(user):
    qs = Lead.objects.select_related("assigned_to", "created_by")
    if has_capability(user, "leads.view_all"):
        return qs
    if has_capability(user, "leads.view_department"):
        return qs.filter(department=user.department)
    if has_capability(user, "leads.view_won"):
        return qs.filter(status=LeadStatus.WON)
    if has_capability(user, "leads.view_own"):
        return qs.filter(assigned_to=user)
    return qs.none()


def can_edit_lead(user, lead: Lead) -> bool:
    if has_capability(user, "leads.edit_all"):
        return True
    if has_capability(user, "leads.edit_department"):
        return lead.department == user.department
    if has_capability(user, "leads.edit_own"):
        return lead.assigned_to_id == user.id
    return False


def can_assign(user) -> bool:
    return has_capability(user, "leads.assign")


def visible_tasks(user):
    qs = Task.objects.select_related("assigned_to", "created_by", "lead")
    if has_capability(user, "tasks.view_all"):
        return qs
    if has_capability(user, "tasks.view_department"):
        return qs.filter(
            Q(assigned_to__department=user.department)
            | Q(assigned_to=user) | Q(created_by=user) | Q(subscribers=user)
            | Q(group__members=user) | Q(group__owner=user)
        ).distinct()
    return qs.filter(
        Q(assigned_to=user) | Q(created_by=user) | Q(subscribers=user)
        | Q(group__members=user) | Q(group__owner=user)
    ).distinct()


def can_edit_task(user, task: Task) -> bool:
    if has_capability(user, "tasks.view_all"):
        return True
    if has_capability(user, "tasks.view_department") and task.assigned_to.department == user.department:
        return True
    return task.assigned_to_id == user.id or task.created_by_id == user.id


def can_assign_tasks(user) -> bool:
    return has_capability(user, "tasks.assign")
