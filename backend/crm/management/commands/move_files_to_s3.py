"""Copy every existing upload from the local disk into S3.

Run ONCE after switching AWS_STORAGE_BUCKET_NAME on, so files uploaded before
the switch are not left behind:

    python manage.py move_files_to_s3 --dry-run
    python manage.py move_files_to_s3

Files that are already in S3, or whose local copy no longer exists (the ones
the container wiped), are reported and skipped -- nothing is deleted.
"""
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.management.base import BaseCommand, CommandError

from crm.models import LeadDocument, TaskAttachment
from hr.models import LeaveRequest
from webforms.models import SubmissionFile
from workspace.models import Notice

TARGETS = [
    (TaskAttachment, "file"),
    (LeadDocument, "file"),
    (LeaveRequest, "document"),
    (Notice, "attachment"),
    (SubmissionFile, "file"),
]


class Command(BaseCommand):
    help = "Copy existing uploads from the local disk into the configured S3 bucket."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="List what would move, change nothing.")

    def handle(self, *args, **opts):
        if not getattr(settings, "USE_S3", False):
            raise CommandError(
                "S3 is not configured — set AWS_STORAGE_BUCKET_NAME first.")
        local = FileSystemStorage(location=settings.MEDIA_ROOT)
        dry = opts["dry_run"]
        moved = missing = already = 0

        for model, field in TARGETS:
            for row in model.objects.exclude(**{field: ""}).exclude(**{f"{field}__isnull": True}):
                name = getattr(row, field).name
                if not name:
                    continue
                if default_storage.exists(name):
                    already += 1
                    continue
                if not local.exists(name):
                    missing += 1
                    self.stdout.write(self.style.WARNING(
                        f"  gone from disk: {model.__name__} #{row.pk} {name}"))
                    continue
                self.stdout.write(f"  {'would copy' if dry else 'copying'}: {name}")
                if not dry:
                    with local.open(name) as fh:
                        default_storage.save(name, ContentFile(fh.read()))
                moved += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n{moved} {'to copy' if dry else 'copied'} · {already} already in S3 · "
            f"{missing} lost before the switch"))
