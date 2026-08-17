"""User model with CarTrends CRM roles.

Six internal roles. Permissions are derived from the role in
`accounts.permissions` -- there is no per-user permission editing in v1,
which keeps the matrix auditable.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    SALES_MANAGER = "sales_manager", "Sales Manager"
    SALES_EXECUTIVE = "sales_executive", "Sales Executive"
    PURCHASE = "purchase", "Purchase Team"
    ACCOUNTS = "accounts", "Accounts"
    SUPPORT = "support", "Customer Support"
    HR_MANAGER = "hr_manager", "HR Manager"


class Department(models.TextChoices):
    SALES = "sales", "Sales"
    PURCHASE = "purchase", "Purchase"
    ACCOUNTS = "accounts", "Accounts"
    SUPPORT = "support", "Customer Support"
    HR = "hr", "Human Resources"
    MANAGEMENT = "management", "Management"


ROLE_DEFAULT_DEPARTMENT = {
    Role.ADMIN: Department.MANAGEMENT,
    Role.SALES_MANAGER: Department.SALES,
    Role.SALES_EXECUTIVE: Department.SALES,
    Role.PURCHASE: Department.PURCHASE,
    Role.ACCOUNTS: Department.ACCOUNTS,
    Role.SUPPORT: Department.SUPPORT,
    Role.HR_MANAGER: Department.HR,
}


class User(AbstractUser):
    # username, first_name, last_name, email, password, is_active from AbstractUser
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SALES_EXECUTIVE)
    department = models.CharField(max_length=20, choices=Department.choices, default=Department.SALES)
    whatsapp_phone = models.CharField(
        max_length=20, blank=True, default="",
        help_text="E.164, e.g. 9198XXXXXXXX -- used for WhatsApp notifications once the API is configured.",
    )
    reporting_manager = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reports",
    )

    @property
    def is_admin_role(self) -> bool:
        return self.role == Role.ADMIN

    def save(self, *args, **kwargs):
        if self.role == Role.ADMIN:
            # Admin role always maps onto Django's staff/superuser flags so
            # /admin and admin-only API checks agree with each other.
            self.is_staff = True
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
