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
    # Always 200 fast -- Meta retries on anything else.
    return JsonResponse({"status": "ok", "ingested": created})


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
