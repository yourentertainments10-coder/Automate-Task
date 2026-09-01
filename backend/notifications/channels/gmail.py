"""Gmail API sender (users.messages.send via REST, OAuth refresh-token flow).

Fully written but INERT until the NEW credentials for this project are set:
    GMAIL_ENABLED=true
    GMAIL_CLIENT_ID=...        (from the new Google OAuth client)
    GMAIL_CLIENT_SECRET=...
    GMAIL_REFRESH_TOKEN=...    (granted with gmail.send scope)
    GMAIL_SENDER=crm@yourdomain.com

No Google SDK dependency -- plain REST keeps the footprint small.
"""
import base64
import logging
import os
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

log = logging.getLogger(__name__)

_token_cache = {"access_token": "", "expires_at": 0.0}


def _cfg():
    return {
        "enabled": os.environ.get("GMAIL_ENABLED", "false").lower() == "true",
        "client_id": os.environ.get("GMAIL_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GMAIL_CLIENT_SECRET", "").strip(),
        "refresh_token": os.environ.get("GMAIL_REFRESH_TOKEN", "").strip(),
        "sender": os.environ.get("GMAIL_SENDER", "").strip(),
    }


def is_configured() -> bool:
    c = _cfg()
    return c["enabled"] and all(c[k] for k in ("client_id", "client_secret", "refresh_token", "sender"))


def _access_token() -> str | None:
    if _token_cache["access_token"] and _token_cache["expires_at"] > time.time() + 60:
        return _token_cache["access_token"]
    c = _cfg()
    try:
        res = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": c["client_id"],
            "client_secret": c["client_secret"],
            "refresh_token": c["refresh_token"],
            "grant_type": "refresh_token",
        }, timeout=15)
        if res.status_code != 200:
            log.warning("Gmail token refresh failed %s: %s", res.status_code, res.text[:300])
            return None
        data = res.json()
        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = time.time() + int(data.get("expires_in", 3600))
        return _token_cache["access_token"]
    except requests.RequestException as exc:
        log.warning("Gmail token refresh exception: %s", exc)
        return None


APP_BASE_URL = os.environ.get(
    "APP_BASE_URL", "https://automatetask.onrender.com").rstrip("/")


def _html_email(body: str, link: str, label: str) -> str:
    """Plain body + one big button. People read these on a phone: the whole
    point is to go straight to the task, not to hunt for it in the app."""
    from html import escape
    url = link if link.startswith("http") else f"{APP_BASE_URL}{link}"
    lines = "".join(
        f"<div style='margin:0 0 6px'>{escape(l) if l.strip() else '&nbsp;'}</div>"
        for l in body.split("\n"))
    return f"""<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;font-size:15px;
            color:#1a221f;line-height:1.5;max-width:560px">
  {lines}
  <div style="margin:22px 0 6px">
    <a href="{escape(url)}"
       style="display:inline-block;background:#0d7a5f;color:#ffffff;
              text-decoration:none;font-weight:700;font-size:15px;
              padding:13px 26px;border-radius:10px">{escape(label)}</a>
  </div>
  <div style="color:#66716c;font-size:12px;margin-top:14px">
    Or paste this into your browser:<br>
    <a href="{escape(url)}" style="color:#0d7a5f">{escape(url)}</a>
  </div>
</div>"""


def send_email(to_email: str, subject: str, body: str,
               link: str = "", link_label: str = "Open in Automate Task") -> dict:
    if not to_email:
        return {"channel": "gmail", "status": "skipped", "detail": "user has no email"}
    if not is_configured():
        return {"channel": "gmail", "status": "skipped", "detail": "not configured"}
    token = _access_token()
    if not token:
        return {"channel": "gmail", "status": "error", "detail": "token refresh failed"}

    if link:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(_html_email(body, link, link_label), "html", "utf-8"))
    else:
        msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = to_email
    msg["from"] = _cfg()["sender"]
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    try:
        res = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json={"raw": raw},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if res.status_code < 300:
            # Self-addressed mail (a user registered with the SENDER mailbox)
            # lands pre-read — flip it back to unread so it isn't missed.
            if to_email.strip().lower() == _cfg()["sender"].lower():
                msg_id = res.json().get("id")
                if msg_id:
                    requests.post(
                        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}/modify",
                        json={"addLabelIds": ["UNREAD", "INBOX"]},
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=15,
                    )
            return {"channel": "gmail", "status": "sent", "detail": ""}
        log.warning("Gmail send failed %s: %s", res.status_code, res.text[:300])
        return {"channel": "gmail", "status": "error", "detail": f"HTTP {res.status_code}"}
    except requests.RequestException as exc:
        return {"channel": "gmail", "status": "error", "detail": str(exc)[:200]}
