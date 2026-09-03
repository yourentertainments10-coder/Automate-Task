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
    # There is no customer-support post: product/other support IS the Sales
    # post; tech support is the IT Lead post. Developer team is separate.
    SALES_EXECUTIVE = "sales_executive", "Sales"
    PURCHASE_MANAGER = "purchase_manager", "Purchase Manager"
    PURCHASE = "purchase", "Purchase Team"
    ACCOUNTS_MANAGER = "accounts_manager", "Accounts Manager"
    ACCOUNTS = "accounts", "Accounts"
    IT_LEAD = "it_lead", "IT Lead"
    DEVELOPER_MANAGER = "developer_manager", "Developer Manager"
    DEVELOPER = "developer", "Developer"
    WAREHOUSE_MANAGER = "warehouse_manager", "Warehouse Manager"
    WAREHOUSE = "warehouse", "Warehouse Team"
    RIDER = "rider", "Rider"
    HOUSEKEEPING = "housekeeping", "Housekeeping"
    SECURITY = "security", "Security"
    LEGAL = "legal", "Legal"
    HR_EXECUTIVE = "hr_executive", "HR Executive"
    HR_MANAGER = "hr_manager", "HR Manager"


class Department(models.TextChoices):
    SALES = "sales", "Sales"
    PURCHASE = "purchase", "Purchase"
    ACCOUNTS = "accounts", "Accounts"
    SUPPORT = "support", "IT Team"
    DEVELOPMENT = "development", "Developer Team"
    WAREHOUSE = "warehouse", "Warehouse"
    HR = "hr", "Human Resources"
    MANAGEMENT = "management", "Management"


class DepartmentOption(models.Model):
    """Admin-managed department list.

    The `Department` choices above stay as the seed and as the constants the
    code refers to (ROLE_DEFAULT_DEPARTMENT, scoping...). This table is what
    the dropdowns actually read, so Admin can add a department -- or rename
    one -- without a deploy. `code` is what gets stored on users/tasks/leads.
    """
    code = models.SlugField(max_length=20, unique=True)
    name = models.CharField(max_length=60)
    active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    @classmethod
    def choices_list(cls):
        """(code, name) for every active department, seeded rows included."""
        rows = list(cls.objects.filter(active=True))
        if not rows:                       # before the seed migration runs
            return list(Department.choices)
        return [(d.code, d.name) for d in rows]

    @classmethod
    def label_for(cls, code):
        if not code:
            return ""
        row = cls.objects.filter(code=code).first()
        return row.name if row else dict(Department.choices).get(code, code)


ROLE_DEFAULT_DEPARTMENT = {
    Role.ADMIN: Department.MANAGEMENT,
    Role.SALES_MANAGER: Department.SALES,
    Role.SALES_EXECUTIVE: Department.SALES,
    Role.PURCHASE_MANAGER: Department.PURCHASE,
    Role.PURCHASE: Department.PURCHASE,
    Role.ACCOUNTS_MANAGER: Department.ACCOUNTS,
    Role.ACCOUNTS: Department.ACCOUNTS,
    Role.IT_LEAD: Department.SUPPORT,
    Role.DEVELOPER_MANAGER: Department.DEVELOPMENT,
    Role.DEVELOPER: Department.DEVELOPMENT,
    Role.WAREHOUSE_MANAGER: Department.WAREHOUSE,
    Role.WAREHOUSE: Department.WAREHOUSE,
    Role.RIDER: Department.WAREHOUSE,
    Role.HOUSEKEEPING: Department.WAREHOUSE,
    Role.SECURITY: Department.WAREHOUSE,
    Role.LEGAL: Department.MANAGEMENT,
    Role.HR_EXECUTIVE: Department.HR,
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
