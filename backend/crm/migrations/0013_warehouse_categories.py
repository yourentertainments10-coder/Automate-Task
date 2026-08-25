"""Seed task categories for the new Warehouse department."""
from django.db import migrations

CATS = ["Loading", "Unloading", "Packing", "Stock Count", "Dispatch Run",
        "Rider Delivery", "Warehouse Cleaning"]


def seed(apps, schema_editor):
    TaskCategory = apps.get_model("crm", "TaskCategory")
    existing = {(c.department, c.name.lower())
                for c in TaskCategory.objects.all()}
    for name in CATS:
        if ("warehouse", name.lower()) not in existing:
            TaskCategory.objects.create(name=name, department="warehouse")


class Migration(migrations.Migration):
    dependencies = [("crm", "0012_it_dev_categories")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
