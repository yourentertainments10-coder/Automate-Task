"""E3: AI layer for tasks — Claude behind AI_ENABLED, deterministic fallback
ALWAYS works (same contract as intake.ai: the app never blocks on AI).

  draft_task(prompt)          -> {"title", "description", "checklist", "provider"}
  summarize_task(task, feed)  -> {"summary", "provider"}
  review_sentence(stats)      -> str  (pure rules — Sir's categories, so the
                                 no-API-key install says the same things)
"""
import json
import logging
import os
import re

import requests

log = logging.getLogger(__name__)

DRAFT_SYSTEM = """You draft internal CRM tasks for an Indian auto-parts trading business.
From the user's request, reply with ONLY a JSON object:
{"title": "<max 12 words, imperative>",
 "description": "<2-4 sentences: what exactly to do and what done looks like>",
 "checklist": ["<3-6 short tickable steps>"]}"""

SUMMARY_SYSTEM = """You summarize one CRM task's state for a busy manager.
Reply with ONLY a JSON object: {"summary": "<3-5 short sentences: what the task is,
where it stands, what happened recently, what should happen next>"}"""


def _claude_enabled() -> bool:
    return (os.environ.get("AI_ENABLED", "false").lower() == "true"
            and bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()))


def _claude_json(system: str, user: str) -> dict | None:
    try:
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"].strip(),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
                "max_tokens": 700,
                "system": system,
                "messages": [{"role": "user", "content": user[:6000]}],
            },
            timeout=int(os.environ.get("AI_TIMEOUT_SECONDS", "20")),
        )
        if res.status_code != 200:
            log.warning("Claude API %s: %s", res.status_code, res.text[:200])
            return None
        reply = "".join(b.get("text", "") for b in res.json().get("content", []))
        match = re.search(r"\{.*\}", reply, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception:  # noqa: BLE001 -- AI must never break the feature
        log.exception("Claude draft/summarize failed")
        return None


# ---------------------------------------------------------------------------

def draft_task(prompt: str) -> dict:
    prompt = (prompt or "").strip()
    if _claude_enabled():
        data = _claude_json(DRAFT_SYSTEM, prompt)
        if data and data.get("title"):
            return {
                "title": str(data["title"])[:200],
                "description": str(data.get("description", ""))[:2000],
                "checklist": [str(s)[:200] for s in (data.get("checklist") or [])][:8],
                "provider": "claude",
            }
    # deterministic fallback: first sentence -> title, steps split on
    # newlines / "then" / commas / "aur"
    first = re.split(r"[.\n!?]", prompt, 1)[0].strip()
    title = " ".join(first.split()[:12]).capitalize() or "New task"
    steps = [s.strip(" -•\t") for s in
             re.split(r"\n|,| then | and then | aur | phir ", prompt) if s.strip(" -•\t")]
    checklist = [" ".join(s.split()[:10]).capitalize() for s in steps[1:6]] \
        if len(steps) > 1 else []
    return {"title": title, "description": prompt[:2000],
            "checklist": checklist, "provider": "rules"}


def summarize_task(task, feed) -> dict:
    lines = [f"{a.created_at:%d %b}: {a.text}" for a in feed[:15]]
    if _claude_enabled():
        data = _claude_json(SUMMARY_SYSTEM, (
            f"Task {task.code}: {task.title}\nStatus: {task.status} · "
            f"Priority: {task.priority} · Due: {task.due_at or '—'}\n"
            f"Assigned to: {task.assigned_to}\nDescription: {task.description[:500]}\n"
            f"Progress: {task.progress_percent or 0}% · effort {task.effort_minutes or '?'}m "
            f"assigned, {task.actual_minutes or 0}m spent\nRecent history:\n" + "\n".join(lines)))
        if data and data.get("summary"):
            return {"summary": str(data["summary"])[:1500], "provider": "claude"}
    parts = [f"{task.code} “{task.title}” is {task.get_status_display().lower()}"
             + (f", {task.progress_percent}% done" if task.progress_percent else "") + "."]
    if task.due_at:
        parts.append(f"Due {task.due_at:%d %b %H:%M}.")
    if task.effort_minutes:
        parts.append(f"Assigned effort {task.effort_minutes}m"
                     + (f", {task.actual_minutes}m spent so far" if task.actual_minutes else "") + ".")
    if lines:
        parts.append("Latest: " + lines[0].split(": ", 1)[-1] + ".")
    return {"summary": " ".join(parts), "provider": "rules"}


def review_sentence(r: dict) -> str:
    """Sir's review categories, computed from the D1–D4 stats. Pure rules —
    identical output with or without an API key."""
    completed, on_time = r["completed"], r["on_time_rate"]
    if completed == 0:
        return "No completions in this period — check the pipeline before judging."
    if on_time is None:
        # everything they finished was self-assigned, so nothing is scored
        return ("Only self-assigned work finished here — nothing to score. "
                "Delegate them real tasks to judge performance.")
    if on_time is not None and on_time >= 90 and (r["score"] or 0) >= 85:
        return ("Next level — on time every time. Make them a trainer/lead; "
                "consider promotion.")
    if r["multitask_days"] >= 3 and (on_time or 0) < 70:
        return ("Multitasker but below expected speed — train them, or reduce "
                "parallel load.")
    if (on_time or 0) < 50 or r["overdue"] > r["total"] / 2:
        return "Slow — give one task at a time and review daily."
    return "Steady — keep the current load, review effort values."
