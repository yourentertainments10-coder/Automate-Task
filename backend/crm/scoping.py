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


# ---------------------------------------------------------------------------
# Task assignment hierarchy (Sir's rule, 18 Aug meeting):
# level-based, NOT department-based. You may assign to your own level and
# below -- never upward. Cross-department assignment is explicitly fine.
#   Admin(3) -> anyone.  Managers(2) -> managers + employees.
#   Employees(1) -> fellow employees.  Self-assign always allowed.
# ---------------------------------------------------------------------------
from accounts.models import Role

ROLE_LEVEL = {Role.ADMIN: 3, Role.SALES_MANAGER: 2, Role.HR_MANAGER: 2}


def assignment_level(user) -> int:
    return ROLE_LEVEL.get(user.role, 1)


def can_assign_to(assigner, assignee) -> bool:
    if assigner.pk == assignee.pk:
        return True
    return assignment_level(assigner) >= assignment_level(assignee)


def assignable_users(user):
    """Active users this person may assign tasks to (their level and below)."""
    from accounts.models import User
    qs = User.objects.filter(is_active=True)
    my_level = assignment_level(user)
    if my_level >= 3:
        return qs
    allowed_roles = [role for role in Role if ROLE_LEVEL.get(role, 1) <= my_level]
    return qs.filter(role__in=allowed_roles)


def visible_tasks(user, include_deleted=False):
    qs = Task.objects.select_related("assigned_to", "created_by", "lead")
    if not include_deleted:
        qs = qs.filter(deleted_at__isnull=True)
    if has_capability(user, "tasks.view_all"):
        return qs
    # The designated reporting manager sees ALL their direct reports' tasks,
    # whoever assigned them and whatever the department (reviewer's rule).
    reports_clause = Q(assigned_to__reporting_manager=user)
    if has_capability(user, "tasks.view_department"):
        return qs.filter(
            Q(assigned_to__department=user.department)
            | Q(assigned_to=user) | Q(created_by=user) | Q(subscribers=user)
            | Q(group__members=user) | Q(group__owner=user) | reports_clause
        ).distinct()
    return qs.filter(
        Q(assigned_to=user) | Q(created_by=user) | Q(subscribers=user)
        | Q(group__members=user) | Q(group__owner=user) | reports_clause
    ).distinct()


def can_edit_task(user, task: Task) -> bool:
    if has_capability(user, "tasks.view_all"):
        return True
    if has_capability(user, "tasks.view_department") and task.assigned_to.department == user.department:
        return True
    return task.assigned_to_id == user.id or task.created_by_id == user.id


def can_assign_tasks(user) -> bool:
    return has_capability(user, "tasks.assign")
