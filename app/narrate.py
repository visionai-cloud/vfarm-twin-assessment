"""Turn the deterministic 24h summary into human-readable narration.

The LLM is a *pure consumer* of the already-computed summary: it never touches
the store, and it can only rephrase facts we hand it. If no API key is set (or
the call fails), we fall back to a deterministic template so the endpoint always
works, offline and in tests.

Split for testability:
  * build_prompt()          -> pure (LLM input)
  * template_narration()    -> pure (the fallback prose)
  * narrate()               -> the only function that does I/O (OpenAI call)
"""
from __future__ import annotations

import json
from typing import Optional

from .config import settings
from .log import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "You are the narrator for a digital vertical farm. Given a structured "
    "summary of the last 24 hours, write a concise operations briefing of 3-5 "
    "sentences. Lead with the most urgent blocker if there is one. Only state "
    "facts present in the data — never invent pods, numbers, or events. Be plain "
    "and specific; no marketing tone."
)


def build_prompt(summary: dict) -> str:
    """The user message handed to the model: the summary as compact JSON."""
    payload = {
        "window_start": _iso(summary.get("window_start")),
        "window_end": _iso(summary.get("window_end")),
        "total_events": summary.get("total_events", 0),
        "by_type": summary.get("by_type", {}),
        "by_location": summary.get("by_location", {}),
        "counts": summary.get("counts", {}),
        "blockers": [_slim(e) for e in summary.get("blockers", [])],
        "successes": [_slim(e) for e in summary.get("successes", [])],
        "experiments": [_slim(e) for e in summary.get("experiments", [])],
    }
    return "Summarize the last 24 hours in the farm:\n" + json.dumps(payload, default=str)


def template_narration(summary: dict) -> str:
    """Deterministic fallback prose — no LLM required."""
    total = summary.get("total_events", 0)
    if total == 0:
        return "No events were logged in the farm in the last 24 hours."

    counts = summary.get("counts", {})
    n_locations = len(summary.get("by_location", {}) or {})
    parts = [
        f"In the last 24 hours the farm logged {total} "
        f"event{_s(total)} across {n_locations} location{_s(n_locations)}."
    ]

    blockers = summary.get("blockers", [])
    if blockers:
        lead = blockers[0]
        verb = "needs" if len(blockers) == 1 else "need"
        parts.append(
            f"{len(blockers)} blocker{_s(len(blockers))} {verb} attention — most notably "
            f"{lead.get('location', 'unknown')}: {lead.get('notes') or lead.get('event_type')}."
        )

    successes = summary.get("successes", [])
    if successes:
        parts.append(f"{len(successes)} success{_es(len(successes))} logged.")

    experiments = summary.get("experiments", [])
    if experiments:
        exp = experiments[0]
        parts.append(
            f"{len(experiments)} experiment{_s(len(experiments))} running, "
            f"including in {exp.get('location', 'unknown')}."
        )
    return " ".join(parts)


def narrate(summary: dict) -> dict:
    """Return narration + provenance. Uses OpenAI if configured, else template."""
    if not settings.openai_api_key:
        return {
            "narration": template_narration(summary),
            "generated_by": "fallback",
            "model": None,
        }
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.3,
            # GPT-5-family models require max_completion_tokens (not max_tokens);
            # it's accepted by current 4o models too.
            max_completion_tokens=300,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(summary)},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            raise ValueError("empty completion")
        return {"narration": text, "generated_by": "openai", "model": settings.openai_model}
    except Exception as exc:  # network / auth / quota -> never fail the endpoint
        logger.warning("narration LLM unavailable (%s); using template fallback", type(exc).__name__)
        return {
            "narration": template_narration(summary),
            "generated_by": "fallback",
            "model": None,
            "note": f"llm unavailable, used template ({type(exc).__name__})",
        }


# --- helpers ---
def _iso(value) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _slim(event: dict) -> dict:
    return {
        "location": event.get("location"),
        "event_type": event.get("event_type"),
        "notes": event.get("notes"),
        "tags": event.get("tags"),
    }


def _s(n: int) -> str:
    return "" if n == 1 else "s"


def _es(n: int) -> str:
    return "" if n == 1 else "es"
