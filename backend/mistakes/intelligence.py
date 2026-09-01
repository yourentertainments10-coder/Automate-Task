"""What the register works out on its own, and what it asks the AI.

The split is deliberate and it matters:

  RULES decide anything that carries a consequence. Counting occurrences,
  crossing the PIP threshold, spawning the corrective task, telling a manager
  to run training -- these must give the same answer every single time, be
  explainable to the person they affect, and never depend on a model being up.

  The AI only SUGGESTS. It reads free text and offers a category, finds
  similar past mistakes, drafts corrective/preventive action, and gives an
  opinion on human-error-vs-process-failure. Every one of those lands as a
  suggestion a human accepts or overrides. If the model is down or wrong, the
  register still works exactly as before.

Nobody is ever disciplined by a language model here.
"""
import logging
import re
from datetime import timedelta

from django.utils import timezone

from config import llm

log = logging.getLogger(__name__)

# --- thresholds: plain numbers, so an employee can be shown the arithmetic ---
REPEAT_WINDOW_DAYS = 365      # how far back a repeat counts
TRAINING_AT = 2               # same category twice -> manager runs training
PIP_AT = 3                    # three times -> formal performance plan


# ===========================================================================
# RULES -- deterministic, no model involved
# ===========================================================================

def prior_mistakes(mistake, days=REPEAT_WINDOW_DAYS):
    """This person's earlier mistakes in the same category, newest first."""
    from .models import Mistake
    return (Mistake.objects
            .filter(employee=mistake.employee,
                    category__iexact=mistake.category,
                    created_at__gte=timezone.now() - timedelta(days=days))
            .exclude(pk=mistake.pk)
            .order_by("-created_at"))


def occurrence_count(mistake) -> int:
    """How many times this category has come up for this person, counting
    the current one. Pure counting -- this is what drives every threshold."""
    return prior_mistakes(mistake).count() + 1


def escalation_for(count: int) -> dict:
    """What the count alone says should happen. A manager still decides."""
    if count >= PIP_AT:
        return {"level": 3, "needs_training": True, "suggest_pip": True,
                "why": f"{count}th time in this category — the pattern is not "
                       "closing with coaching alone."}
    if count >= TRAINING_AT:
        return {"level": 2, "needs_training": True, "suggest_pip": False,
                "why": f"{count}nd time in this category — training is due "
                       "before it becomes a habit."}
    return {"level": 1, "needs_training": False, "suggest_pip": False,
            "why": "First time — coach, correct and move on."}


def sop_for(mistake):
    """The written process this mistake should be judged against."""
    from .models import SOP
    if mistake.sop_id:
        return mistake.sop
    qs = SOP.objects.filter(active=True)
    if mistake.category:
        hit = qs.filter(category__iexact=mistake.category)
        if mistake.department:
            hit = hit.filter(department__in=[mistake.department, ""])
        if hit.exists():
            return hit.first()
    if mistake.department:
        return qs.filter(department=mistake.department).first()
    return None


# ===========================================================================
# AI -- suggestions only, every one overridable
# ===========================================================================

CATEGORY_SYSTEM = """You file workplace mistakes for an Indian auto-parts business.
Pick the ONE category from the allowed list that best fits, even when the
wording differs from previous entries ("part name galat", "wrong item name"
and "typed description instead of code" are all the same category).
Reply with ONLY JSON:
{"category": "<exactly one from the allowed list>",
 "confidence": <0-100>,
 "why": "<one short sentence>"}"""

CAPA_SYSTEM = """You advise a manager closing a workplace mistake.
Corrective action fixes THIS instance. Preventive action stops it recurring
and must change something durable -- a check, a field, a sequence, a
handover -- never "be more careful".
Reply with ONLY JSON:
{"corrective": "<one or two sentences, concrete>",
 "preventive": "<one or two sentences, concrete>",
 "training_topic": "<short topic, or empty string>"}"""

JUDGE_SYSTEM = """You compare what a person says they did against the written
process, and decide which of these it was:
  human_error    - the process covered this and was clear; a step was skipped
  process_failure- the process never said to do it, or was ambiguous
  unclear        - the account or the process is too thin to tell
Never guess to be helpful: choose "unclear" when the evidence is thin.
Reply with ONLY JSON:
{"verdict": "human_error|process_failure|unclear",
 "confidence": <0-100>,
 "reason": "<one or two sentences citing the step involved>",
 "process_gap": "<what the process should say, or empty string>"}"""


def suggest_category(description: str, allowed: list[str]) -> dict | None:
    """Match free text onto the managed category list. Returns None when the
    AI is off, unreachable, or names a category that does not exist."""
    if not (llm.enabled() and description.strip() and allowed):
        return None
    data = llm.chat_json(
        CATEGORY_SYSTEM,
        "Allowed categories: " + ", ".join(allowed)
        + "\n\nMistake description:\n" + description[:1500],
        max_tokens=200)
    if not data:
        return None
    picked = str(data.get("category", "")).strip()
    match = next((c for c in allowed if c.lower() == picked.lower()), None)
    if not match:
        return None
    return {"category": match,
            "confidence": _pct(data.get("confidence")),
            "why": str(data.get("why", ""))[:200],
            "provider": llm.provider()}


def similar_past_mistakes(mistake, limit: int = 5) -> list[dict]:
    """Earlier mistakes that look like this one even when worded differently.

    Word overlap does the first pass (cheap and always available); the AI
    only re-ranks what that found, so this degrades to a keyword search
    rather than to nothing.
    """
    from .models import Mistake
    pool = list(Mistake.objects
                .filter(created_at__gte=timezone.now() - timedelta(days=REPEAT_WINDOW_DAYS))
                .exclude(pk=mistake.pk)
                .order_by("-created_at")[:120])
    if not pool:
        return []

    mine = _words(f"{mistake.category} {mistake.description}")
    scored = []
    for m in pool:
        overlap = mine & _words(f"{m.category} {m.description}")
        if not overlap:
            continue
        score = len(overlap) / max(len(mine), 1)
        if m.employee_id == mistake.employee_id:
            score += 0.25                       # same person matters more
        if m.category and m.category.lower() == (mistake.category or "").lower():
            score += 0.25
        scored.append((score, m, sorted(overlap)[:6]))
    scored.sort(key=lambda r: -r[0])

    return [{"id": m.pk, "code": m.code, "category": m.category,
             "description": m.description[:160],
             "employee": (m.employee.get_full_name() or m.employee.username)
                         if m.employee else None,
             "same_person": m.employee_id == mistake.employee_id,
             "shared_words": words,
             "created_at": m.created_at}
            for score, m, words in scored[:limit]]


def suggest_capa(mistake, count: int) -> dict | None:
    """Draft corrective + preventive action for a manager to edit."""
    if not llm.enabled():
        return None
    sop = sop_for(mistake)
    lines = [
        f"Mistake: {mistake.description[:800]}",
        f"Category: {mistake.category or 'not set'}",
        f"Times this category has come up for this person: {count}",
    ]
    if mistake.explanation:
        lines.append(f"The person's explanation: {mistake.explanation[:600]}")
    if mistake.root_cause:
        lines.append(f"Stated root cause: {mistake.get_root_cause_display()}")
    if sop:
        lines += ["", "The written process:", sop.as_prompt()[:1800]]
    data = llm.chat_json(CAPA_SYSTEM, "\n".join(lines), max_tokens=400)
    if not data:
        return None
    return {"corrective": str(data.get("corrective", ""))[:600],
            "preventive": str(data.get("preventive", ""))[:600],
            "training_topic": str(data.get("training_topic", ""))[:120],
            "provider": llm.provider()}


def judge_human_or_process(mistake) -> dict | None:
    """Human error or process failure? Needs BOTH the person's account and a
    written process -- without either there is nothing to compare, and the
    honest answer is to say so rather than invent a verdict."""
    sop = sop_for(mistake)
    if not sop:
        return {"verdict": "unclear", "confidence": 0,
                "reason": "No written process is on file for this job, so there "
                          "is nothing to judge the account against.",
                "process_gap": f"Write the process for '{mistake.category or 'this job'}' "
                               "in Mistakes > Processes.",
                "provider": "rules"}
    if not mistake.explanation.strip():
        return {"verdict": "unclear", "confidence": 0,
                "reason": "The person has not explained what they did yet.",
                "process_gap": "", "provider": "rules"}
    if not llm.enabled():
        return None
    data = llm.chat_json(
        JUDGE_SYSTEM,
        "\n".join([sop.as_prompt()[:2200], "",
                   f"WHAT HAPPENED: {mistake.description[:600]}",
                   f"WHAT THE PERSON SAYS THEY DID: {mistake.explanation[:900]}"]),
        max_tokens=350)
    if not data:
        return None
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in ("human_error", "process_failure", "unclear"):
        verdict = "unclear"
    return {"verdict": verdict, "confidence": _pct(data.get("confidence")),
            "reason": str(data.get("reason", ""))[:400],
            "process_gap": str(data.get("process_gap", ""))[:300],
            "sop": sop.title, "sop_version": sop.version,
            "provider": llm.provider()}


# --- small helpers ---------------------------------------------------------

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
        "was", "not", "he", "she", "it", "this", "that", "with", "by", "from",
        "did", "has", "have", "been", "at", "as", "but", "so", "we", "i"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOP}


def _pct(value) -> int:
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return 0
