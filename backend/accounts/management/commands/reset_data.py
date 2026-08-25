"""Wipe ALL demo/test business data and load the real CarTrends team.

    python manage.py reset_data --yes            # wipe + create real users
    python manage.py reset_data --yes --no-users # wipe only

Keeps: configuration (task/mistake categories, holidays, settings, office
locations, leave types, task templates, directory) and the `admin` account
as a fallback login. Everything else goes. Take a dumpdata backup first —
this is permanent.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Role, User

# name, email, username, first_name, last_name, role, department
# Passwords follow Sir's rule: <FirstName>@2026 (first name exactly as listed,
# honorifics dropped). Roles inferred from the email / title — edit in the
# app (My Team) if any need changing.
REAL_TEAM = [
    ("Amit Kumar", "amit.singh@cartrends.in", "amit", "Amit", "Kumar", Role.SALES_EXECUTIVE, "sales"),
    ("Anuj IT Intern", "developer.team@cartrends.in", "anuj", "Anuj", "IT Intern", Role.ADMIN, "management"),
    # One person, two mailboxes (accounts@ + finance@) — finance@ is his
    # unique address so email-login works; accounts@ stays Kesar's.
    ("Anurag", "finance@cartrends.net", "anurag", "Anurag", "", Role.ACCOUNTS, "accounts"),
    ("Arun Sharma", "arun.sharma@cartrends.in", "arun", "Arun", "Sharma", Role.SALES_EXECUTIVE, "sales"),
    ("Bhagwan Ji", "Bhagwanshaysharma449@gmail.com", "bhagwan", "Bhagwan", "Ji", Role.SALES_EXECUTIVE, "sales"),
    ("Bhawna Singh", "bhawna.singh@cartrends.in", "bhawna", "Bhawna", "Singh", Role.SALES_EXECUTIVE, "sales"),
    ("Tarun", "hr@cartrends.net", "tarun", "Tarun", "", Role.HR_MANAGER, "hr"),
    ("Gunjan Sales CRM", "gunjan.sales@cartrends.in", "gunjan", "Gunjan", "", Role.SALES_EXECUTIVE, "sales"),
    ("Harsh Singh", "interns@cartrends.net", "harsh", "Harsh", "Singh", Role.SALES_EXECUTIVE, "sales"),
    ("Islam Alam", "Alam@cartrends.net", "islam", "Islam", "Alam", Role.SALES_EXECUTIVE, "sales"),
    ("Jagdish kumar", "jagdish.kumar@cartrends.in", "jagdish", "Jagdish", "Kumar", Role.SALES_EXECUTIVE, "sales"),
    ("Jaibir", "jaibir.jitu@cartrends.in", "jaibir", "Jaibir", "", Role.SALES_EXECUTIVE, "sales"),
    ("Karan Rathore", "karan.intern@cartrends.in", "karan", "Karan", "Rathore", Role.SALES_EXECUTIVE, "sales"),
    ("Kesar Pal", "accounts@cartrends.co.in", "kesar", "Kesar", "Pal", Role.ACCOUNTS, "accounts"),
    ("Mahesh", "maheshshokeen6@gmail.com", "mahesh", "Mahesh", "", Role.WAREHOUSE, "warehouse"),
    ("Mr. NK Jain", "chairmandesk@cartrends.net", "nkjain", "NK", "Jain", Role.ADMIN, "management"),
    ("Nirmal Singla", "nirmal.singh@cartrends.in", "nirmal", "Nirmal", "Singla", Role.SALES_EXECUTIVE, "sales"),
    ("Prateek Sir", "foundersteam@cartrends.net", "prateek", "Prateek", "", Role.ADMIN, "management"),
    ("Rahul Bhandari", "rahul.bhandari@cartrends.in", "rahul.bhandari", "Rahul", "Bhandari", Role.WAREHOUSE, "warehouse"),
    ("Rahul Sinha", "Bijwasan@cartrends.net", "rahul.sinha", "Rahul", "Sinha", Role.WAREHOUSE_MANAGER, "warehouse"),
    ("Rahul Thakur", "rahulthakur3928@gmail.com", "rahul.thakur", "Rahul", "Thakur", Role.RIDER, "warehouse"),
    ("Ramprasad Pandey", "ram.prasad@cartrends.in", "ramprasad", "Ramprasad", "Pandey", Role.SALES_EXECUTIVE, "sales"),
    ("Ronak", "ronak.sales@cartrends.in", "ronak", "Ronak", "", Role.SALES_EXECUTIVE, "sales"),
    ("Ronit Netwal", "ronit.netwal@cartrends.in", "ronit", "Ronit", "Netwal", Role.SALES_EXECUTIVE, "sales"),
    ("Roshan Mishra", "roshan.mishra@cartrends.in", "roshan", "Roshan", "Mishra", Role.SALES_EXECUTIVE, "sales"),
    ("Sandeep Tiwari", "sandeep.tiwari@cartrends.in", "sandeep", "Sandeep", "Tiwari", Role.SALES_EXECUTIVE, "sales"),
    ("Satya Prakash", "satya.prakash@cartrends.in", "satya", "Satya", "Prakash", Role.SALES_EXECUTIVE, "sales"),
    ("Sidhant", "sidhant.lakhan@cartrends.in", "sidhant", "Sidhant", "", Role.SALES_EXECUTIVE, "sales"),
    ("Sohit kumar", "Sohit.kumar@cartrends.in", "sohit", "Sohit", "Kumar", Role.SALES_EXECUTIVE, "sales"),
    ("Surendra", "surendra.shyoran@cartrends.in", "surendra", "Surendra", "", Role.SALES_EXECUTIVE, "sales"),
    ("Thakur Dass", "Bijwasan@cartrends.net", "thakur", "Thakur", "Dass", Role.WAREHOUSE_MANAGER, "warehouse"),
    ("Ujit", "ujit.kumar@cartrends.in", "ujit", "Ujit", "", Role.WAREHOUSE, "warehouse"),
    ("Ujjawal", "ujjwal.jain@cartrends.in", "ujjawal", "Ujjawal", "", Role.SALES_EXECUTIVE, "sales"),
    ("Vinit", "itsupport@cartrends.net", "vinit", "Vinit", "", Role.IT_LEAD, "support"),
    ("Sourav", "", "sourav", "Sourav", "", Role.WAREHOUSE, "warehouse"),
    ("Mukesh", "", "mukesh", "Mukesh", "", Role.WAREHOUSE, "warehouse"),
    ("Narendra", "", "narendra", "Narendra", "", Role.WAREHOUSE, "warehouse"),
    ("Anil", "", "anil", "Anil", "", Role.WAREHOUSE, "warehouse"),
    ("Rahul Tyagi", "", "rahul.tyagi", "Rahul", "Tyagi", Role.WAREHOUSE, "warehouse"),
    ("Kuldeep", "", "kuldeep", "Kuldeep", "", Role.RIDER, "warehouse"),
]


class Command(BaseCommand):
    help = "PERMANENTLY wipe demo/test data and load the real team."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="confirm the wipe")
        parser.add_argument("--no-users", action="store_true", help="wipe only")
        parser.add_argument("--drop-admin", action="store_true",
                            help="also delete the fallback 'admin' account (real admins exist)")

    @transaction.atomic
    def handle(self, *args, **opts):
        if not opts["yes"]:
            raise CommandError("Refusing without --yes (this is permanent; back up first).")

        from crm.models import (Lead, Task, TaskActivity, TaskAttachment,
                                TaskChangeRequest, TaskChecklistItem, Quotation,
                                LeadEvent, LeadDocument, AssignmentRule)
        from mistakes.models import Mistake, MistakeEvent
        from notifications.models import Notification
        from intake.models import InboundMessage
        from webforms.models import Form, FormSubmission, SubmissionFile
        from workspace.models import (Group, Notice, NoticeRead, LinkCollection,
                                      Link, Idea, IdeaComment)
        from hr.models import Attendance, AttendanceCorrection, LeaveRequest, FaceProfile
        from payroll.models import SalaryStructure, Advance, PayrollRun, Payslip
        from rest_framework_simplejwt.token_blacklist.models import (
            OutstandingToken, BlacklistedToken)

        wiped = {}
        # children first, then parents (FKs without CASCADE are few, but be explicit)
        for model in (MistakeEvent, Mistake,
                      TaskChecklistItem, TaskAttachment, TaskChangeRequest,
                      TaskActivity, Task,
                      Quotation, LeadDocument, LeadEvent, Lead,
                      SubmissionFile, FormSubmission, Form,
                      IdeaComment, Idea, Link, LinkCollection, NoticeRead, Notice, Group,
                      Payslip, PayrollRun, Advance, SalaryStructure,
                      AttendanceCorrection, LeaveRequest, Attendance, FaceProfile,
                      InboundMessage, Notification,
                      BlacklistedToken, OutstandingToken):
            n, _ = model.objects.all().delete()
            wiped[model.__name__] = n
        # routing rules keep their config, lose their (deleted) members
        AssignmentRule.objects.all().update(member_ids=[], rr_index=0)

        n_users, _ = User.objects.exclude(username="admin").delete()
        wiped["User (non-admin)"] = n_users

        created = []
        if not opts["no_users"]:
            for _, email, username, first, last, role, dept in REAL_TEAM:
                u = User.objects.create_user(
                    username, email, f"{first}@2026",
                    first_name=first, last_name=last, role=role, department=dept,
                )
                if role == Role.ADMIN:
                    u.is_staff = True
                    u.is_superuser = True
                    u.save(update_fields=["is_staff", "is_superuser"])
                created.append(username)

        kept = "+ admin kept"
        if opts["drop_admin"] and not opts["no_users"]:
            User.objects.filter(username="admin").delete()
            kept = "admin removed — Prateek / NK Jain / Anuj are the admins"

        for k, v in wiped.items():
            if v:
                self.stdout.write(f"  wiped {v:>4}  {k}")
        self.stdout.write(self.style.SUCCESS(
            f"Done. {len(created)} real users created ({kept})."))
