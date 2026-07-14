"""Ingestion service — the single funnel both sources flow through.

Source A (webhook) and Source B (sheet poller) both call `ingest_events`.
Everything upstream of this is "get raw dicts"; everything here down is
normalize -> tag -> append. New sources reuse this untouched.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .log import get_logger
from .models import SCHEMA_VERSION, FarmEvent
from .normalize import normalize_event
from .tagging import derive_tags

logger = get_logger(__name__)


def _new_id() -> str:
    return str(uuid.uuid4())


def build_event(source: str, raw_payload: dict, *, now: datetime) -> FarmEvent:
    """Pure-ish assembler: raw dict -> a FarmEvent row (not yet persisted)."""
    norm = normalize_event(source, raw_payload, now=now)
    tags = derive_tags(norm["event_type"], norm["notes"])
    return FarmEvent(
        id=_new_id(),
        source=norm["source"],
        source_event_id=norm["source_event_id"],
        dedup_hash=norm["dedup_hash"],
        event_time=norm["event_time"],
        received_at=now,
        event_type=norm["event_type"],
        location=norm["location"],
        notes=norm["notes"],
        tags=tags,
        raw_payload=raw_payload,
        normalized=_normalized_view(norm, tags),
        schema_version=SCHEMA_VERSION,
    )


def _normalized_view(norm: dict, tags: list[str]) -> dict:
    return {
        "event_time": norm["event_time"].isoformat(),
        "event_type": norm["event_type"],
        "location": norm["location"],
        "notes": norm["notes"],
        "tags": tags,
    }


def ingest_events(session: Session, source: str, raw_payloads: list[dict]) -> dict:
    """Append a batch. Idempotent: rows whose dedup_hash already exists are
    skipped, never overwritten. Returns a summary of what happened.
    """
    now = datetime.now(timezone.utc)
    stored_ids: list[str] = []
    duplicates = 0

    # Dedup within the incoming batch first (same event twice in one payload).
    seen_in_batch: set[str] = set()
    candidates: list[FarmEvent] = []
    for raw in raw_payloads:
        event = build_event(source, raw, now=now)
        if event.dedup_hash in seen_in_batch:
            duplicates += 1
            continue
        seen_in_batch.add(event.dedup_hash)
        candidates.append(event)

    # Fast path: skip hashes we already know about (one round-trip).
    if candidates:
        hashes = [e.dedup_hash for e in candidates]
        existing = set(
            session.scalars(
                select(FarmEvent.dedup_hash).where(FarmEvent.dedup_hash.in_(hashes))
            ).all()
        )
        for event in candidates:
            if event.dedup_hash in existing:
                duplicates += 1
                continue
            # Safety net for the check-then-insert race: a concurrent request
            # may insert the same dedup_hash between our SELECT and INSERT. The
            # UNIQUE constraint is the source of truth; a savepoint lets us
            # absorb the collision as a duplicate without aborting the batch.
            try:
                with session.begin_nested():
                    session.add(event)
                stored_ids.append(event.id)
            except IntegrityError:
                duplicates += 1
        session.commit()

    logger.info(
        "ingest source=%s stored=%d duplicates=%d", source, len(stored_ids), duplicates
    )
    return {"stored": len(stored_ids), "duplicates": duplicates, "ids": stored_ids}
