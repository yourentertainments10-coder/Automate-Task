"""Seed a default admin (and optional demo team) for local development.

    python manage.py seed_users                 # admin only
    python manage.py seed_users --demo-team     # + one user per role
"""
from django.core.management.base import BaseCommand

from accounts.models import ROLE_DEFAULT_DEPARTMENT, Role, User

DEMO_TEAM = [
    ("rahul",  "Rahul",  "Sharma", Role.SALES_EXECUTIVE),
    ("amit",   "Amit",   "Verma",  Role.SALES_EXECUTIVE),
    ("priya",  "Priya",  "Singh",  Role.SALES_EXECUTIVE),
    ("meera",  "Meera",  "Iyer",   Role.SALES_MANAGER),
    ("vikram", "Vikram", "Rao",    Role.PURCHASE),
    ("anita",  "Anita",  "Desai",  Role.ACCOUNTS),
    ("karan",  "Karan",  "Mehta",  Role.SUPPORT),
]


class Command(BaseCommand):
    help = "Seed default admin and optional demo team (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--demo-team", action="store_true")
        parser.add_argument("--admin-password", default="admin@12345")

    def handle(self, *args, **opts):
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                "admin", "admin@cartrends.net", opts["admin_password"],
                role=Role.ADMIN, department="management", first_name="Admin",
            )
            self.stdout.write(self.style.SUCCESS("Created admin (password: %s)" % opts["admin_password"]))
        else:
            self.stdout.write("admin already exists")

        if opts["demo_team"]:
            for username, first, last, role in DEMO_TEAM:
                if User.objects.filter(username=username).exists():
                    continue
                User.objects.create_user(
                    username, f"{username}@cartrends.net", f"{username}@12345",
                    first_name=first, last_name=last, role=role,
                    department=ROLE_DEFAULT_DEPARTMENT[role],
                )
                self.stdout.write(self.style.SUCCESS(f"Created {username} ({role})"))
