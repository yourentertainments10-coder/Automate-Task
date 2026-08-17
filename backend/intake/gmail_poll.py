"""Gmail inbox poller: unread messages -> InboundMessage -> pipeline.

Uses the same OAuth refresh-token credentials as the Gmail sender
(notifications/channels/gmail.py) but needs the gmail.modify scope so it
can mark messages read after ingesting them. Inert until GMAIL_ENABLED=true.
"""
import base64
import logging
import os
import re

import requests

from notifications.channels.gmail import _access_token, is_configured

from .models import InboundMessage
from .pipeline import process_message

log = logging.getLogger(__name__)

API = "https://gmail.googleapis.com/gmail/v1/users/me"


def poll_inbox(max_messages: int = 10) -> int:
    if not is_configured():
        return 0
    token = _access_token()
    if not token:
        return 0
    headers = {"Authorization": f"Bearer {token}"}
    query = os.environ.get("GMAIL_POLL_QUERY", "is:unread in:inbox category:primary")

    res = requests.get(f"{API}/messages", params={"q": query, "maxResults": max_messages},
                       headers=headers, timeout=20)
    if res.status_code != 200:
        log.warning("Gmail list failed %s: %s", res.status_code, res.text[:200])
        return 0

    ingested = 0
    for ref in res.json().get("messages", []) or []:
        mid = ref["id"]
        if InboundMessage.objects.filter(channel="gmail", external_id=mid).exists():
            _mark_read(mid, headers)
            continue
        detail = requests.get(f"{API}/messages/{mid}", params={"format": "full"},
                              headers=headers, timeout=20)
        if detail.status_code != 200:
            continue
        data = detail.json()
        head = {h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", [])}
        sender_raw = head.get("from", "")
        m = re.match(r"(?:\"?([^\"<]*)\"?\s*)?<?([^<>\s]+@[^<>\s]+)>?", sender_raw)
        sender_name, sender_email = (m.group(1) or "").strip() if m else "", (m.group(2) if m else sender_raw)

        msg = InboundMessage.objects.create(
            channel=InboundMessage.Channel.GMAIL,
            external_id=mid,
            sender=sender_email,
            sender_name=sender_name,
            subject=head.get("subject", "")[:300],
            body=_extract_text(data.get("payload", {}))[:8000],
        )
        process_message(msg)
        _mark_read(mid, headers)
        ingested += 1
    return ingested


def _extract_text(payload: dict) -> str:
    if payload.get("mimeType", "").startswith("text/plain"):
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "===").decode(errors="replace")
    for part in payload.get("parts", []) or []:
        text = _extract_text(part)
        if text:
            return text
    return ""


def _mark_read(mid: str, headers: dict):
    requests.post(f"{API}/messages/{mid}/modify",
                  json={"removeLabelIds": ["UNREAD"]}, headers=headers, timeout=15)
