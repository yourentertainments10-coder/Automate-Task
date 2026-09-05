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
import time
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
            "gemini": "gemini-3.5-flash-lite",
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


def chat(system: str, user: str, max_tokens: int = 700,
         timeout: int | None = None) -> str | None:
    """Raw completion text, or None if anything at all goes wrong.

    `timeout` overrides AI_TIMEOUT_SECONDS for calls where somebody is
    watching a spinner -- a voice note is worth waiting for, a background
    digest is not.
    """
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
                timeout=timeout or _timeout(),
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
            timeout=timeout or _timeout(),
        )
        if res.status_code != 200:
            log.warning("AI (%s) %s: %s", who, res.status_code, res.text[:200])
            return None
        return res.json()["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001 -- the AI must never break a feature
        log.warning("AI (%s) call failed", who, exc_info=True)
        return None


# Gemini takes audio directly on its native endpoint, so a voice note needs
# no second vendor. Anything else: no transcription, and the caller says so.
GEMINI_NATIVE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def audio_model() -> str:
    """The model used for voice.

    A model built for transcription beats a general chat model at it, and
    costs less. Pinned separately from AI_MODEL so the text side can move
    without touching speech.
    """
    # Measured on Hinglish clips: the general flash model got the name, the
    # time and the effort right where the cheaper transcribe-only model turned
    # "do ghante" into "dukaan". A wrong deadline is worse than a slow one.
    return ((os.environ.get("AI_AUDIO_MODEL") or "").strip()
            or ("gemini-3.5-flash" if provider() == "gemini" else model()))


def can_transcribe() -> bool:
    return enabled() and provider() == "gemini"


def transcribe(audio: bytes, mime: str, hint: str = "") -> str | None:
    """Speech -> text. Returns None on any failure, never raises.

    The prompt asks for the words as spoken: staff here mix Hindi and English
    in one sentence, and a model that "helpfully" translates to English throws
    away the half the reader recognises.
    """
    if not can_transcribe() or not audio:
        return None
    import base64
    system = (
        "Write out exactly what is said in this recording.\n"
        "Keep Hindi and Hinglish words as spoken -- do not translate.\n"
        "Write Hindi in Roman letters, the way people type it.\n"
        "Keep names, part numbers and amounts exactly.\n"
        "Reply with the words only: no quotes, no commentary, no timestamps."
    )
    if hint:
        system += f"\nNames you may hear: {hint}"
    body = {"contents": [{"parts": [
        {"text": system},
        {"inline_data": {"mime_type": mime or "audio/webm",
                         "data": base64.b64encode(audio).decode()}},
    ]}]}
    try:
        # 503 means "busy, try again" in Gemini's own words, and it happens
        # often enough that one retry turns a dead button into a slow one.
        # 429 is a quota wall -- retrying there only makes it worse.
        for attempt in (1, 2):
            res = requests.post(
                GEMINI_NATIVE.format(model=audio_model()),
                params={"key": _key()}, json=body, timeout=max(_timeout(), 60),
            )
            if res.status_code != 503 or attempt == 2:
                break
            time.sleep(2)
        if res.status_code != 200:
            log.warning("transcribe %s: %s", res.status_code, res.text[:200])
            return None
        parts = res.json()["candidates"][0]["content"]["parts"]
        # A general model answers in "text"; the dedicated transcribe model
        # answers in "audioTranscription". Read both, so swapping AI_AUDIO_MODEL
        # never silently returns nothing.
        text = "".join(
            p.get("text") or (p.get("audioTranscription") or {}).get("text") or ""
            for p in parts).strip()
        return text or None
    except Exception:  # noqa: BLE001 -- a failed voice note must not break the form
        log.warning("transcribe failed", exc_info=True)
        return None


def chat_json(system: str, user: str, max_tokens: int = 700,
              timeout: int | None = None) -> dict | None:
    """Same, but pull the first JSON object out of the reply. Smaller models
    like to wrap JSON in prose or a ```json fence, so both are handled."""
    reply = chat(system, user, max_tokens, timeout)
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
