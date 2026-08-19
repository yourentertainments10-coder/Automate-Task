"""Seed the managed category list and import any category names already
typed free-text on existing tasks (as global categories, so nothing that
was in use disappears from the dropdown)."""
from django.db import migrations

DEFAULTS = {
    "": [  # global — offered to every department
        "Calls", "Follow-up", "Data Entry", "Training", "Meeting",
        "Documentation", "Review",
    ],
    "sales": ["Quotes", "Customer Visit", "Order Processing", "Collections"],
    "purchase": ["Vendor Follow-up", "Purchase Order", "Stock Check", "Price Comparison"],
    "accounts": ["Invoicing", "Payments", "Reconciliation", "GST Filing"],
    "support": ["Complaint", "Warranty", "Delivery Issue", "Customer Query"],
    "hr": ["Onboarding", "Attendance Fix", "Payroll", "Recruitment"],
    "management": ["Planning", "Reporting", "Audit"],
}


def seed(apps, schema_editor):
    TaskCategory = apps.get_model("crm", "TaskCategory")
    Task = apps.get_model("crm", "Task")

    existing = {(c.department, c.name.lower()) for c in TaskCategory.objects.all()}

    def add(name, department=""):
        key = (department, name.lower())
        if key not in existing:
            TaskCategory.objects.create(name=name, department=department)
            existing.add(key)

    for department, names in DEFAULTS.items():
        for name in names:
            add(name, department)

    # keep every already-used free-text value available (global)
    for name in (Task.objects.exclude(category="")
                 .values_list("category", flat=True).distinct()):
        if not any(k[1] == name.strip().lower() for k in existing):
            add(name.strip()[:60])


def unseed(apps, schema_editor):
    pass  # keep data on rollback


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0007_task_department_taskchangerequest_escalated_and_more"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
