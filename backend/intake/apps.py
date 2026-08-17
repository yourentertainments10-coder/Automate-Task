import os
import sys
import threading

from django.apps import AppConfig


class IntakeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "intake"

    def ready(self):
        # Gmail inbox poller -- only spins up when Gmail is actually
        # configured, so local dev without credentials runs zero threads.
        if os.environ.get("GMAIL_ENABLED", "false").lower() != "true":
            return
        serving = any(cmd in sys.argv for cmd in ("runserver", "gunicorn")) or "gunicorn" in sys.argv[0]
        if not serving:
            return

        interval = int(os.environ.get("GMAIL_POLL_SECONDS", "120"))

        def tick():
            import time
            from .gmail_poll import poll_inbox
            while True:
                time.sleep(interval)
                try:
                    poll_inbox()
                except Exception:  # noqa: BLE001 -- keep the poller alive
                    import logging
                    logging.getLogger(__name__).exception("gmail poll failed")

        threading.Thread(target=tick, daemon=True, name="gmail-poller").start()
