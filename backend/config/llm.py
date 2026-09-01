"""One LLM client for the whole app.

The provider is inferred from the key so nobody has to keep two sets of
settings in step: an ``nvapi-`` key means NVIDIA's OpenAI-compatible
endpoint, ``sk-ant-`` means Anthropic. AI_PROVIDER overrides the guess.

Every call returns None on any failure -- a missing key, a cold model, a
timeout, bad JSON. Callers always have a rules-based fallback, so the AI
being down must never break a feature.
"""
import json
import logging
import os
import re

import requests

log = logging.getLogger(__name__)

NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# NVIDIA's hosted models cold-start: the first call after an idle spell can
# take a minute. Anthropic answers in a few seconds.
DEFAULT_TIMEOUT = {"nvidia": 90, "anthropic": 30, "openai": 30,
                   "openrouter": 60, "groq": 30, "gemini": 30, "together": 60}


def _key() -> str:
    return (os.environ.get("AI_API_KEY")
            or os.environ.get("NVIDIA_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def provider() -> str:
    explicit = os.environ.get("AI_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    key = _key()
    for prefix, name in (("nvapi-", "nvidia"), ("sk-ant-", "anthropic"),
                         ("sk-or-", "openrouter"), ("gsk_", "groq"),
                         ("AIza", "gemini"), ("hf_", "huggingface")):
        if key.startswith(prefix):
            return name
    return "openai" if key.startswith("sk-") else "anthropic"


def model() -> str:
    name = (os.environ.get("AI_MODEL") or os.environ.get("ANTHROPIC_MODEL") or "").strip()
    if name and not (provider() == "nvidia" and name.startswith("claude")):
        return name
    return {"nvidia": "nvidia/nemotron-3-nano-30b-a3b",
            "openai": "gpt-4o-mini",
            "groq": "llama-3.3-70b-versatile",
            "gemini": "gemini-2.0-flash-lite",
            "openrouter": "google/gemma-3-27b-it:free",
            }.get(provider(), "claude-sonnet-5")


def enabled() -> bool:
    return os.environ.get("AI_ENABLED", "false").lower() == "true" and bool(_key())


def _timeout() -> int:
    raw = os.environ.get("AI_TIMEOUT_SECONDS", "").strip()
    if raw.isdigit():
        return int(raw)
    return DEFAULT_TIMEOUT.get(provider(), 30)


# Every one of these speaks the OpenAI chat format, so switching provider is
# a key + a base URL, never a code change.
OPENAI_COMPATIBLE = {
    "nvidia": NVIDIA_URL,
    "openai": "https://api.openai.com/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "together": "https://api.together.xyz/v1/chat/completions",
}


def _chat_url(who: str) -> str:
    """AI_BASE_URL wins, so a provider we have never heard of still works."""
    override = os.environ.get("AI_BASE_URL", "").strip().rstrip("/")
    if override:
        return override if override.endswith("/chat/completions")             else f"{override}/chat/completions"
    return OPENAI_COMPATIBLE.get(who, OPENAI_COMPATIBLE["openai"])


def chat(system: str, user: str, max_tokens: int = 700) -> str | None:
    """Raw completion text, or None if anything at all goes wrong."""
    if not enabled():
        return None
    key, who = _key(), provider()
    try:
        if who == "anthropic":
            res = requests.post(
                ANTHROPIC_URL,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": model(), "max_tokens": max_tokens, "system": system,
                      "messages": [{"role": "user", "content": user[:6000]}]},
                timeout=_timeout(),
            )
            if res.status_code != 200:
                log.warning("AI (%s) %s: %s", who, res.status_code, res.text[:200])
                return None
            return "".join(b.get("text", "") for b in res.json().get("content", []))

        # NVIDIA, OpenRouter, Groq, Gemini's compat endpoint and OpenAI itself
        # all speak the same chat format, so one branch serves them all.
        url = _chat_url(who)
        res = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model(), "max_tokens": max_tokens, "temperature": 0.2,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user[:6000]}]},
            timeout=_timeout(),
        )
        if res.status_code != 200:
            log.warning("AI (%s) %s: %s", who, res.status_code, res.text[:200])
            return None
        return res.json()["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001 -- the AI must never break a feature
        log.warning("AI (%s) call failed", who, exc_info=True)
        return None


def chat_json(system: str, user: str, max_tokens: int = 700) -> dict | None:
    """Same, but pull the first JSON object out of the reply. Smaller models
    like to wrap JSON in prose or a ```json fence, so both are handled."""
    reply = chat(system, user, max_tokens)
    if not reply:
        return None
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", reply.strip(), flags=re.MULTILINE)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        log.warning("AI returned unparsable JSON: %s", text[:200])
        return None
