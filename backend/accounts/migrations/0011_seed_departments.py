"""Seed the managed department list from the original hard-coded choices, so
nothing changes on day one and Admin can edit the list from Settings after."""
from django.db import migrations


def seed(apps, schema_editor):
    DepartmentOption = apps.get_model("accounts", "DepartmentOption")
    rows = [
        ("sales", "Sales"), ("purchase", "Purchase"), ("accounts", "Accounts"),
        ("support", "IT Team"), ("development", "Developer Team"),
        ("warehouse", "Warehouse"), ("hr", "Human Resources"),
        ("management", "Management"),
    ]
    for order, (code, name) in enumerate(rows, start=1):
        DepartmentOption.objects.update_or_create(
            code=code, defaults={"name": name, "order": order * 10, "active": True})


def unseed(apps, schema_editor):
    apps.get_model("accounts", "DepartmentOption").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_departmentoption")]
    operations = [migrations.RunPython(seed, unseed)]
