from django.core.management.base import BaseCommand

from intake.gmail_poll import poll_inbox


class Command(BaseCommand):
    help = "Poll the Gmail inbox once and run new messages through the intake pipeline."

    def handle(self, *args, **opts):
        n = poll_inbox()
        self.stdout.write(self.style.SUCCESS(f"Ingested {n} email(s)."))
