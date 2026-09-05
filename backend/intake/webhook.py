"""Meta WhatsApp Cloud API webhook.

GET  /api/webhooks/whatsapp  -- Meta's one-time verification handshake
POST /api/webhooks/whatsapp  -- message delivery (X-Hub-Signature-256 checked
                                against WHATSAPP_APP_SECRET when set)

Point the NEW Meta app's webhook at:
    https://<your-render-host>/api/webhooks/whatsapp
with the same verify token you put in WHATSAPP_WEBHOOK_VERIFY_TOKEN.
"""
import hashlib
import hmac
import json
import logging
import os

from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import InboundMessage
from .pipeline import process_message

log = logging.getLogger(__name__)


def _verify_signature(raw: bytes, header: str | None) -> bool:
    secret = os.environ.get("WHATSAPP_APP_SECRET", "").strip()
    if not secret:
        log.warning("WHATSAPP_APP_SECRET unset -- webhook signature NOT verified (dev only)")
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    if request.method == "GET":
        token = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "").strip()
        if (
            request.GET.get("hub.mode") == "subscribe"
            and token
            and request.GET.get("hub.verify_token") == token
        ):
            return HttpResponse(request.GET.get("hub.challenge", ""))
        return HttpResponseForbidden("verify token mismatch")

    if not _verify_signature(request.body, request.headers.get("X-Hub-Signature-256")):
        return HttpResponseForbidden("bad signature")

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"status": "bad json"}, status=400)

    created = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "")
                        for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                created += _ingest(m, contacts)
            # Meta reports delivered / read / failed on the same webhook.
            # These used to be dropped, which is why "did it arrive?" had no
            # answer -- our record stopped at "Meta accepted it".
            for s in value.get("statuses", []):
                _record_status(s)
    # Always 200 fast -- Meta retries on anything else.
    return JsonResponse({"status": "ok", "ingested": created})


def _record_status(s: dict) -> None:
    """One delivery update from Meta. Never raises: a webhook that errors is
    retried for days."""
    from notifications.delivery import WhatsAppDelivery
    wamid, status = s.get("id", ""), s.get("status", "")
    if not wamid or not status:
        return
    detail = ""
    for err in s.get("errors", []) or []:
        detail = f"{err.get('code', '')} {err.get('title', '')} {err.get('message', '')}".strip()
        break
    try:
        row = WhatsAppDelivery.objects.filter(wamid=wamid).first()
        if not row:
            return                       # sent before this table existed
        # Meta can deliver callbacks out of order; never walk a message
        # backwards from read to sent.
        rank = {"accepted": 0, "sent": 1, "delivered": 2, "read": 3, "failed": 4}
        if rank.get(status, 0) < rank.get(row.status, 0) and status != "failed":
            return
        row.status = status
        if detail:
            row.detail = detail[:500]
        row.save(update_fields=["status", "detail", "updated_at"])
    except Exception:                    # noqa: BLE001
        log.warning("could not record delivery status", exc_info=True)


def _ingest(m: dict, contacts: dict) -> int:
    ext_id = m.get("id", "")
    sender = m.get("from", "")
    if not ext_id or not sender:
        return 0
    if InboundMessage.objects.filter(channel="whatsapp", external_id=ext_id).exists():
        return 0  # Meta redelivery -- already handled

    body, media = "", []
    mtype = m.get("type")
    if mtype == "text":
        body = m.get("text", {}).get("body", "")
    elif mtype in ("image", "document", "audio", "video"):
        blob = m.get(mtype, {})
        body = blob.get("caption", "") or f"[{mtype} received]"
        media = [{"id": blob.get("id", ""), "mime_type": blob.get("mime_type", ""),
                  "caption": blob.get("caption", ""), "kind": mtype}]
    else:
        body = f"[{mtype} message]"

    msg = InboundMessage.objects.create(
        channel=InboundMessage.Channel.WHATSAPP,
        external_id=ext_id,
        sender=sender,
        sender_name=contacts.get(sender, ""),
        body=body,
        media=media,
    )
    process_message(msg)
    return 1
