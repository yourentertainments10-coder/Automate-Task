from django.core.management.base import BaseCommand

from crm.reminders import send_followup_reminders


class Command(BaseCommand):
    help = "Send follow-up-due notifications for overdue open leads (idempotent per follow-up)."

    def handle(self, *args, **opts):
        sent = send_followup_reminders()
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} follow-up reminder(s)."))
