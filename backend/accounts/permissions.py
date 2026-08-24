"""Role -> capability matrix for the whole CRM.

One place to answer "who can do what". Views use the small DRF permission
classes at the bottom; queryset scoping (who SEES which leads) lives in the
crm app's views and also keys off these helpers.
"""
from rest_framework.permissions import BasePermission

from .models import Role

# Capabilities are plain strings so the frontend can receive them verbatim.
ROLE_CAPABILITIES = {
    Role.ADMIN: {
        "users.manage", "leads.view_all", "leads.edit_all", "leads.assign",
        "tasks.view_all", "tasks.assign", "dashboard.view", "settings.manage",
        "quotations.manage", "notifications.view", "intake.view",
        "hr.manage", "hr.approve",
    },
    Role.SALES_MANAGER: {
        "leads.view_department", "leads.edit_department", "leads.assign",
        "tasks.view_department", "tasks.assign", "dashboard.view",
        "quotations.manage", "notifications.view", "intake.view",
        "hr.approve",
    },
    Role.SALES_EXECUTIVE: {
        "leads.view_own", "leads.edit_own", "tasks.view_own",
        "quotations.manage", "notifications.view",
    },
    Role.PURCHASE: {
        "leads.view_department", "tasks.view_own", "notifications.view",
    },
    Role.ACCOUNTS: {
        "leads.view_won", "tasks.view_own", "notifications.view",
    },
    # IT Lead: manager-level over the IT/dev side — assigns tasks, sees the
    # department, reviews requests; no sales-pipeline powers.
    Role.IT_LEAD: {
        "tasks.view_department", "tasks.assign", "dashboard.view",
        "notifications.view", "hr.approve",
    },
    Role.DEVELOPER: {
        "tasks.view_own", "notifications.view",
    },
    # Dedicated HR: full leave/attendance powers company-wide, and no access
    # to the sales pipeline at all (separation of duties).
    Role.HR_MANAGER: {
        "hr.manage", "hr.approve", "users.manage",
        "tasks.view_own", "notifications.view",
    },
}


def capabilities_for(user) -> list[str]:
    return sorted(ROLE_CAPABILITIES.get(user.role, set()))


def has_capability(user, capability: str) -> bool:
    return capability in ROLE_CAPABILITIES.get(user.role, set())


class IsAdmin(BasePermission):
    message = "Admin role required."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == Role.ADMIN)


class HasCapability(BasePermission):
    """Usage: permission_classes = [HasCapability.of("leads.assign")]"""

    capability = ""

    @classmethod
    def of(cls, capability: str):
        return type(f"Has_{capability.replace('.', '_')}", (cls,), {"capability": capability})

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and has_capability(request.user, self.capability)
        )
