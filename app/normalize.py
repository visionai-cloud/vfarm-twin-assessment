"""Pure functions: raw source payload -> normalized event fields.

No I/O, no DB, no clock reads passed in from outside -> trivially unit-testable.
The rule of the pipeline: we CLEAN here, but we never DISCARD. Anything we
can't confidently normalize is preserved in raw_payload and given a safe default
(event_type="other", location="unknown") rather than dropped.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

# Canonical event vocabulary. Synonyms -> canonical. Unknown -> "other".
_TYPE_SYNONYMS = {
    "sensor": "sensor_alert",
    "sensor_alert": "sensor_alert",
    "alert": "sensor_alert",
    "environment": "environment",
    "env": "environment",
    "growth": "growth",
    "harvest": "harvest",
    "builder": "builder_update",
    "builder_update": "builder_update",
    "update": "builder_update",
    "checkin": "builder_update",
    "check-in": "builder_update",
    "experiment": "experiment",
    "maintenance": "maintenance",
}

CANONICAL_TYPES = sorted(set(_TYPE_SYNONYMS.values()) | {"other"})


def normalize_type(raw_type: Any) -> str:
    if not raw_type:
        return "other"
    key = str(raw_type).strip().lower().replace(" ", "_")
    return _TYPE_SYNONYMS.get(key, "other")


def normalize_location(raw_location: Any) -> str:
    """Lowercase, trimmed, space->dash. e.g. 'Pod A / Rack 3' -> 'pod-a-rack-3'."""
    if not raw_location:
        return "unknown"
    text = str(raw_location).strip().lower()
    cleaned = []
    prev_dash = False
    for ch in text:
        if ch.isalnum():
            cleaned.append(ch)
            prev_dash = False
        elif not prev_dash:
            cleaned.append("-")
            prev_dash = True
    return "".join(cleaned).strip("-") or "unknown"


def parse_timestamp(value: Any, *, fallback: datetime) -> datetime:
    """Accept ISO-8601 strings (with or without 'Z') and epoch seconds/millis.

    Always returns a timezone-aware UTC datetime. Unparseable -> `fallback`,
    so a bad timestamp never rejects an otherwise-good event.
    """
    if value is None or value == "":
        return fallback
    # Epoch (int/float, or numeric string).
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        num = float(value)
        if num > 1e12:  # milliseconds
            num /= 1000.0
        return datetime.fromtimestamp(num, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return fallback
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return fallback


def compute_dedup_hash(source: str, source_event_id: Any, raw_payload: dict) -> str:
    """Stable idempotency key.

    Prefer the source's own id (source + source_event_id). If the source gives
    no id, fall back to a content hash of the raw payload so exact re-deliveries
    still collapse to one row.
    """
    if source_event_id:
        basis = f"{source}:{source_event_id}"
    else:
        canonical = json.dumps(raw_payload, sort_keys=True, separators=(",", ":"), default=str)
        basis = f"{source}:{canonical}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def normalize_event(source: str, raw_payload: dict, *, now: datetime) -> dict:
    """Turn a raw payload from any source into the normalized field set.

    `now` is injected (not read from the clock here) so the function stays pure
    and the tests are deterministic.
    """
    source_event_id = raw_payload.get("source_event_id") or raw_payload.get("id")
    event_time = parse_timestamp(raw_payload.get("timestamp"), fallback=now)

    return {
        "source": source,
        "source_event_id": str(source_event_id) if source_event_id is not None else None,
        "dedup_hash": compute_dedup_hash(source, source_event_id, raw_payload),
        "event_time": event_time,
        "event_type": normalize_type(raw_payload.get("type")),
        "location": normalize_location(raw_payload.get("location")),
        "notes": str(raw_payload.get("notes") or "").strip(),
    }
