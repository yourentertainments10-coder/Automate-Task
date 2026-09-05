from django.conf import settings
from django.db import models


class Notification(models.Model):
    """One in-app notification for one user. `channels` records what the
    fan-out did on every configured channel, e.g.
    [{"channel": "whatsapp", "status": "skipped", "detail": "not configured"}]
    so delivery is auditable per notification.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=40)          # lead_assigned, follow_up_due, status_change, ...
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    link = models.CharField(max_length=200, blank=True, default="")
    channels = models.JSONField(default=list, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]

    def __str__(self):
        return f"[{self.type}] {self.title} -> {self.user}"


# Delivery outcomes for WhatsApp live in their own module but must be
# imported here so Django picks the model up.
from .delivery import WhatsAppDelivery  # noqa: E402,F401
