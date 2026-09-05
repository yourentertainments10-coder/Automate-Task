"""What Meta said happened to a WhatsApp message we sent.

A tiny table rather than a JSON scan: the webhook looks a message up by id on
every callback, and an indexed column answers that in one query on both
Postgres and SQLite.
"""
from django.conf import settings
from django.db import models


class WhatsAppDelivery(models.Model):
    """One row per message we sent, updated as Meta reports on it.

    accepted  -> Meta's API took it (what we used to call "sent")
    sent      -> it left Meta
    delivered -> it reached the handset
    read      -> the person opened it
    failed    -> it will never arrive; `detail` says why
    """
    wamid = models.CharField(max_length=128, unique=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                             on_delete=models.SET_NULL, related_name="whatsapp_messages")
    phone = models.CharField(max_length=20, blank=True, default="")
    template = models.CharField(max_length=80, blank=True, default="")
    status = models.CharField(max_length=20, default="accepted")
    detail = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-sent_at"]
        verbose_name_plural = "WhatsApp deliveries"

    def __str__(self):
        return f"{self.phone} {self.status}"
