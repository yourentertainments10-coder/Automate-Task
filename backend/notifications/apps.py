import os
import sys
import threading

from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        # Follow-up reminder ticker. Runs inside the web process (fine for an
        # internal tool); disable with NOTIF_SCHEDULER=false. Never runs for
        # management commands like migrate/test.
        if os.environ.get("NOTIF_SCHEDULER", "true").lower() != "true":
            return
        serving = any(cmd in sys.argv for cmd in ("runserver", "gunicorn")) or "gunicorn" in sys.argv[0]
        if not serving:
            return

        def tick():
            import time
            from crm.reminders import send_followup_reminders
            while True:
                time.sleep(300)  # every 5 minutes
                try:
                    send_followup_reminders()
                except Exception:  # noqa: BLE001 -- keep the ticker alive
                    import logging
                    logging.getLogger(__name__).exception("reminder tick failed")

        threading.Thread(target=tick, daemon=True, name="followup-reminders").start()
