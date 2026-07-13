"""Pure functions: derive tags from a normalized event.

Tags are the *derived* layer — our interpretation, kept separate from both the
raw payload and the normalized facts. Adding a new tag = add a rule here; no
schema change, no migration. That is the "easy to extend" requirement.
"""
from __future__ import annotations

# tag -> keywords that trigger it (matched case-insensitively on type + notes).
TAG_RULES: dict[str, tuple[str, ...]] = {
    "BLOCKER": ("blocked", "blocker", "stuck", "failure", "failed", "down", "error",
                "broken", "leak", "outage", "cannot", "can't", "waiting on"),
    "SUCCESS": ("success", "done", "completed", "resolved", "fixed", "healthy",
                "passed", "harvested", "on track", "green"),
    "EXPERIMENT": ("experiment", "trial", "hypothesis", "a/b", "testing ",
                   "variant", "measuring"),
    "ALERT": ("alert", "critical", "urgent", "threshold", "spike", "warning",
              "high", "low"),
}


def derive_tags(event_type: str, notes: str) -> list[str]:
    """Return sorted, de-duplicated tags for an event.

    Also promotes a couple of structural signals:
      * type == "experiment"   -> [EXPERIMENT]
      * type == "sensor_alert" -> [ALERT]
    """
    haystack = f"{event_type} {notes}".lower()
    tags: set[str] = set()

    for tag, keywords in TAG_RULES.items():
        if any(kw in haystack for kw in keywords):
            tags.add(tag)

    if event_type == "experiment":
        tags.add("EXPERIMENT")
    if event_type == "sensor_alert":
        tags.add("ALERT")

    return sorted(tags)
