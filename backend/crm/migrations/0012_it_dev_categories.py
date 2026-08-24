"""Company structure fix (no customer-support team): the old customer-support
task categories become SALES categories (product support is sales' job), and
the support department — now IT Support — plus the new Developer Team get
their own category sets."""
from django.db import migrations

MOVE_TO_SALES = ["Complaint", "Warranty", "Delivery Issue", "Customer Query"]
NEW = {
    "support": ["System Issue", "Access/Login Issue", "Hardware Issue", "Website Update"],
    "development": ["Feature Development", "Bug Fix", "Testing", "Deployment"],
}


def apply(apps, schema_editor):
    TaskCategory = apps.get_model("crm", "TaskCategory")
    for name in MOVE_TO_SALES:
        TaskCategory.objects.filter(department="support", name__iexact=name) \
            .update(department="sales")
    existing = {(c.department, c.name.lower())
                for c in TaskCategory.objects.all()}
    for dept, names in NEW.items():
        for name in names:
            if (dept, name.lower()) not in existing:
                TaskCategory.objects.create(name=name, department=dept)


class Migration(migrations.Migration):
    dependencies = [("crm", "0011_alter_assignmentrule_department_and_more")]
    operations = [migrations.RunPython(apply, migrations.RunPython.noop)]
