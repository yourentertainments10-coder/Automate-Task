from django.db import models


class InboundMessage(models.Model):
    """Every message that reaches the CRM from outside -- WhatsApp webhook,
    Gmail poller, or the admin simulator. external_id gives idempotency:
    Meta and Gmail both redeliver, and a redelivered id is simply skipped."""

    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        GMAIL = "gmail", "Gmail"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        IGNORED = "ignored", "Ignored"
        FAILED = "failed", "Failed"

    channel = models.CharField(max_length=10, choices=Channel.choices)
    external_id = models.CharField(max_length=200)
    sender = models.CharField(max_length=200)          # phone (wa) or email (gmail)
    sender_name = models.CharField(max_length=200, blank=True, default="")
    subject = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField(blank=True, default="")
    media = models.JSONField(default=list, blank=True)  # [{id, mime_type, caption}] metadata only
    ai_result = models.JSONField(default=dict, blank=True)
    lead = models.ForeignKey("crm.Lead", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="inbound_messages")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["channel", "external_id"], name="uniq_channel_external_id"),
        ]

    def __str__(self):
        return f"[{self.channel}] {self.sender}: {self.body[:40]}"
