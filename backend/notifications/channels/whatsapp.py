"""Meta WhatsApp Cloud API sender (direct Graph API, no BSP).

Fully written but INERT until the NEW credentials for this project are set:
    WHATSAPP_ENABLED=true
    WHATSAPP_ACCESS_TOKEN=...
    WHATSAPP_PHONE_NUMBER_ID=...

Free-form text messages only reach users inside a 24h customer-service
window; business-initiated notifications outside that window need an
approved template -- send_template() covers that once templates exist.
"""
import logging
import os

import requests

log = logging.getLogger(__name__)

GRAPH_VERSION = os.environ.get("WHATSAPP_GRAPH_API_VERSION", "v23.0")


def _cfg():
    return {
        "enabled": os.environ.get("WHATSAPP_ENABLED", "false").lower() == "true",
        "token": os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip(),
        "phone_id": os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip(),
    }


def is_configured() -> bool:
    c = _cfg()
    return c["enabled"] and bool(c["token"]) and bool(c["phone_id"])


def _post(payload: dict) -> dict:
    c = _cfg()
    if not is_configured():
        return {"channel": "whatsapp", "status": "skipped", "detail": "not configured"}
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{c['phone_id']}/messages"
    try:
        res = requests.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {c['token']}"},
            timeout=15,
        )
        if res.status_code < 300:
            return {"channel": "whatsapp", "status": "sent", "detail": ""}
        log.warning("WhatsApp send failed %s: %s", res.status_code, res.text[:300])
        return {"channel": "whatsapp", "status": "error", "detail": f"HTTP {res.status_code}"}
    except requests.RequestException as exc:
        log.warning("WhatsApp send exception: %s", exc)
        return {"channel": "whatsapp", "status": "error", "detail": str(exc)[:200]}


def send_text(to_phone: str, body: str) -> dict:
    if not to_phone:
        return {"channel": "whatsapp", "status": "skipped", "detail": "user has no whatsapp number"}
    return _post({
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"preview_url": False, "body": body[:4000]},
    })


def send_template(to_phone: str, template_name: str, params: list[str], lang: str = "en") -> dict:
    if not to_phone:
        return {"channel": "whatsapp", "status": "skipped", "detail": "user has no whatsapp number"}
    return _post({
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in params],
            }],
        },
    })
