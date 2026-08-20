"""Seed the 29 configurable mistake categories from Sir's 20 Aug spec."""
from django.db import migrations

CATEGORIES = [
    "Data Entry Error", "Purchase Error", "Sales Error", "Billing Error",
    "Inventory Error", "Warehouse Error", "Dispatch Error",
    "Customer Service Error", "CRM Error", "Collection Error",
    "Accounts Error", "HR Error", "Attendance/Discipline Issue",
    "Communication Failure", "SOP Violation", "Missed Deadline",
    "Wrong Information", "Wrong Part Number", "Wrong Quantity",
    "Wrong Price/MRP", "Wrong Customer", "Wrong Address", "Wrong Dispatch",
    "Wrong Invoice", "Duplicate Work", "Approval Bypass",
    "Unauthorized Action", "System/Software Error", "Other",
]


def seed(apps, schema_editor):
    MistakeCategory = apps.get_model("mistakes", "MistakeCategory")
    existing = {c.lower() for c in
                MistakeCategory.objects.values_list("name", flat=True)}
    for name in CATEGORIES:
        if name.lower() not in existing:
            MistakeCategory.objects.create(name=name)


class Migration(migrations.Migration):
    dependencies = [("mistakes", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
