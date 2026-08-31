"""AI classification of inbound messages.

classify(text, sender_name) -> dict with a FIXED shape either way:
    {
      "intent":        "purchase" | "inquiry" | "support" | "spam" | "other",
      "customer_name": str,
      "vehicle":       str,
      "items":         [{"name": str, "quantity": int|null}],
      "priority":      "low" | "normal" | "high" | "urgent",
      "department":    "sales" | "purchase" | "accounts" | "support",
      "summary":       str,
      "provider":      "claude" | "rules",
    }

Claude (Anthropic Messages API over plain REST) runs when AI_ENABLED=true
and an API key is set; anything else -- including a provider error or
malformed reply -- falls back to the deterministic keyword classifier, so
the pipeline NEVER blocks on the AI layer.
"""
import json
import logging
import os
import re

import requests

from config import llm

log = logging.getLogger(__name__)

INTENTS = {"purchase", "inquiry", "support", "spam", "other"}
PRIORITIES = {"low", "normal", "high", "urgent"}
DEPARTMENTS = {"sales", "purchase", "accounts", "support"}

SYSTEM_PROMPT = """You classify incoming customer messages for an Indian auto-parts trading business's CRM.
Reply with ONLY a JSON object, no prose, using exactly this shape:
{"intent": "purchase|inquiry|support|spam|other",
 "customer_name": "<name if the message states one, else empty string>",
 "vehicle": "<vehicle make/model mentioned, else empty string>",
 "items": [{"name": "<part>", "quantity": <int or null>}],
 "priority": "low|normal|high|urgent",
 "department": "sales|purchase|accounts|support",
 "summary": "<one line summary>"}
Rules: parts requests/price asks => intent purchase, department sales. Complaints/warranty/delivery/product issues => intent support, department sales (there is no customer-support team; the sales team handles product support). Technical/system/software/website issues => department support (the IT team). Payment/invoice queries => accounts. Promotions/irrelevant => spam. "urgent"/"immediately"/"breakdown" => priority high or urgent."""



def _classify_ai(text: str, sender_name: str) -> dict | None:
    data = llm.chat_json(
        SYSTEM_PROMPT,
        f"Sender name: {sender_name or 'unknown'}"
        + "\n"
        + f"Message:\n{text[:4000]}",
        max_tokens=500,
    )
    return _normalize(data, provider=llm.provider()) if data else None


# --- deterministic fallback ------------------------------------------------

VEHICLES = [
    "tata 407", "tata ace", "tata 709", "ashok leyland dost", "ashok leyland",
    "eicher pro", "eicher", "mahindra bolero", "mahindra pickup", "mahindra",
    "bharatbenz", "force traveller", "maruti", "hyundai", "tata",
]
SUPPORT_WORDS = ["complaint", "warranty", "defective", "broken", "return", "replace", "not working", "issue", "problem"]
ACCOUNTS_WORDS = ["invoice", "payment", "bill", "gst", "refund", "outstanding", "balance"]
SPAM_WORDS = ["offer!!", "lottery", "click here", "subscribe", "winner"]
URGENT_WORDS = ["urgent", "immediately", "asap", "breakdown", "emergency", "today itself"]
PURCHASE_WORDS = ["need", "want", "require", "quote", "quotation", "price", "rate", "send", "order", "buy", "supply"]

ITEM_SPLIT = re.compile(r",| and | & |\n|;", re.IGNORECASE)
QTY = re.compile(r"(\d+)\s*(?:x|pcs|pieces|nos|units)?\s*(.+)", re.IGNORECASE)


def _classify_rules(text: str, sender_name: str) -> dict:
    low = text.lower()

    if any(w in low for w in SPAM_WORDS):
        intent, department = "spam", "sales"
    elif any(w in low for w in SUPPORT_WORDS):
        intent, department = "support", "support"
    elif any(w in low for w in ACCOUNTS_WORDS):
        intent, department = "inquiry", "accounts"
    elif any(w in low for w in PURCHASE_WORDS):
        intent, department = "purchase", "sales"
    else:
        intent, department = "other", "sales"

    vehicle = next((v for v in VEHICLES if v in low), "")

    items = []
    if intent == "purchase":
        # Strip lead-in ("need", "want...") and the vehicle mention, then split.
        payload = re.sub(r"^(hi|hello|namaste|dear\s+\w+)[,.\s]+", "", low)
        payload = re.sub(r"\b(i\s+)?(need|want|require|please send|send|quote for|price of|quotation for|supply)\b", "", payload)
        payload = payload.replace(f"for {vehicle}", "").replace(vehicle, "") if vehicle else payload
        for chunk in ITEM_SPLIT.split(payload):
            name = chunk.strip(" .!?-")
            if not name or len(name) < 3:
                continue
            qty = None
            m = QTY.match(name)
            if m:
                qty, name = int(m.group(1)), m.group(2).strip()
            items.append({"name": name, "quantity": qty})

    priority = "urgent" if any(w in low for w in URGENT_WORDS) else "normal"
    summary = text.strip().splitlines()[0][:140] if text.strip() else ""

    return _normalize({
        "intent": intent, "customer_name": sender_name or "", "vehicle": vehicle,
        "items": items, "priority": priority, "department": department, "summary": summary,
    }, provider="rules")


def _normalize(data: dict, provider: str) -> dict:
    items = data.get("items") or []
    clean_items = []
    for it in items:
        if isinstance(it, dict) and it.get("name"):
            q = it.get("quantity")
            clean_items.append({"name": str(it["name"])[:100],
                                "quantity": int(q) if isinstance(q, (int, float)) else None})
        elif isinstance(it, str) and it.strip():
            clean_items.append({"name": it.strip()[:100], "quantity": None})
    return {
        "intent": data.get("intent") if data.get("intent") in INTENTS else "other",
        "customer_name": str(data.get("customer_name") or "")[:120],
        "vehicle": str(data.get("vehicle") or "")[:120],
        "items": clean_items[:20],
        "priority": data.get("priority") if data.get("priority") in PRIORITIES else "normal",
        "department": data.get("department") if data.get("department") in DEPARTMENTS else "sales",
        "summary": str(data.get("summary") or "")[:300],
        "provider": provider,
    }


def classify(text: str, sender_name: str = "") -> dict:
    if llm.enabled():
        result = _classify_ai(text, sender_name)
        if result:
            return result
    return _classify_rules(text, sender_name)
