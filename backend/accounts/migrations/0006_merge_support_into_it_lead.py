"""IT Support and IT Lead are the same post — keep 'it_lead'."""
from django.db import migrations


def merge(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="support").update(role="it_lead")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_alter_user_department_alter_user_role")]
    operations = [migrations.RunPython(merge, migrations.RunPython.noop)]
