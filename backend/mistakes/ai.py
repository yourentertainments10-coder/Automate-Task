"""M3: AI assistance for the Mistake Register — SUGGESTS, never decides.

suggest(mistake) -> {"classification", "reasoning", "corrective_action",
                     "preventive_action", "provider"}
Claude runs behind AI_ENABLED (same REST pattern as intake.ai); the
rule-based fallback maps the structured root cause to a classification and
a CAPA template, so the install without an API key gives the same shape.
"""
import json
import logging
import os
import re

import requests

from .models import Classification, RootCause

log = logging.getLogger(__name__)

SYSTEM = """You assist a manager reviewing an employee mistake in an Indian auto-parts
trading company. NEVER blame the employee by default: if the process, system,
training or an external party failed, say so. Reply with ONLY JSON:
{"classification": "human|process|system|management|external",
 "reasoning": "<one sentence>",
 "corrective_action": "<what to do NOW to fix this instance>",
 "preventive_action": "<what must change so it never repeats>"}"""

# root cause -> who/what actually failed
ROOT_TO_CLASS = {
    RootCause.LACK_OF_ATTENTION: Classification.HUMAN,
    RootCause.HUMAN_ERROR: Classification.HUMAN,
    RootCause.SOP_NOT_FOLLOWED: Classification.HUMAN,
    RootCause.SOP_MISSING: Classification.PROCESS,
    RootCause.SOP_UNCLEAR: Classification.PROCESS,
    RootCause.APPROVAL_FAILURE: Classification.PROCESS,
    RootCause.COMMUNICATION: Classification.PROCESS,
    RootCause.LACK_OF_TRAINING: Classification.MANAGEMENT,
    RootCause.MANAGERIAL_FAILURE: Classification.MANAGEMENT,
    RootCause.WORKLOAD: Classification.MANAGEMENT,
    RootCause.TIME_PRESSURE: Classification.MANAGEMENT,
    RootCause.SYSTEM_ISSUE: Classification.SYSTEM,
    RootCause.DATA_ISSUE: Classification.SYSTEM,
    RootCause.WRONG_INFORMATION: Classification.EXTERNAL,
    RootCause.VENDOR_ISSUE: Classification.EXTERNAL,
    RootCause.CUSTOMER_ISSUE: Classification.EXTERNAL,
}

CAPA = {
    Classification.HUMAN: (
        "Correct the affected record/order now and confirm with the customer or vendor.",
        "Add a mandatory self-check step (e.g. part-number verification) before this action."),
    Classification.PROCESS: (
        "Fix this instance and flag the gap to the process owner today.",
        "Write or clarify the SOP step that was missing/unclear, with a required sign-off."),
    Classification.MANAGEMENT: (
        "Reassign or re-prioritise so the employee can correct it properly.",
        "Schedule training / rebalance workload; manager reviews the next 3 similar tasks."),
    Classification.SYSTEM: (
        "Correct the data manually and log the system defect with evidence.",
        "Add validation/automation so the software blocks this input in future."),
    Classification.EXTERNAL: (
        "Correct using verified information and inform the vendor/customer in writing.",
        "Require written confirmation from the external party before acting on their input."),
}


def _claude_enabled() -> bool:
    return (os.environ.get("AI_ENABLED", "false").lower() == "true"
            and bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()))


def _claude(mistake) -> dict | None:
    try:
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"].strip(),
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
                  "max_tokens": 500, "system": SYSTEM,
                  "messages": [{"role": "user", "content": (
                      f"Category: {mistake.category}\nSeverity: {mistake.severity}\n"
                      f"Description: {mistake.description[:1500]}\n"
                      f"Employee explanation: {mistake.explanation[:800] or '—'}\n"
                      f"Root cause chosen: {mistake.get_root_cause_display() or '—'} "
                      f"{mistake.root_cause_note}\nSOP: {mistake.sop_name or '—'} "
                      f"followed={mistake.sop_followed} adequate={mistake.sop_adequate}\n"
                      f"Occurrence level: {mistake.occurrence_level}")}]},
            timeout=int(os.environ.get("AI_TIMEOUT_SECONDS", "20")))
        if res.status_code != 200:
            return None
        reply = "".join(b.get("text", "") for b in res.json().get("content", []))
        m = re.search(r"\{.*\}", reply, re.DOTALL)
        data = json.loads(m.group(0)) if m else None
        if data and data.get("classification") in Classification.values:
            return {k: str(data.get(k, ""))[:600] for k in
                    ("classification", "reasoning", "corrective_action", "preventive_action")}
    except Exception:  # noqa: BLE001
        log.exception("Claude mistake suggestion failed")
    return None


def suggest(mistake) -> dict:
    if _claude_enabled():
        data = _claude(mistake)
        if data:
            return {**data, "provider": "claude"}
    # rules: SOP verdicts first (the most important distinction in the spec)
    if mistake.sop_adequate is False:
        cls, why = Classification.PROCESS, "SOP marked inadequate — the process failed the person."
    elif mistake.sop_followed is False and mistake.sop_adequate:
        cls, why = Classification.HUMAN, "An adequate SOP existed and was not followed."
    elif mistake.root_cause:
        cls = ROOT_TO_CLASS.get(mistake.root_cause, Classification.HUMAN)
        why = f"Root cause '{mistake.get_root_cause_display()}' points at {cls.label.lower()}."
    else:
        cls, why = "", "No explanation yet — ask the employee for the root cause first."
    corrective, preventive = CAPA.get(cls, ("", ""))
    if mistake.occurrence_level >= 2 and preventive:
        preventive += " Repeat error: the manager owns verifying this change landed."
    return {"classification": cls, "reasoning": why,
            "corrective_action": corrective, "preventive_action": preventive,
            "provider": "rules"}
