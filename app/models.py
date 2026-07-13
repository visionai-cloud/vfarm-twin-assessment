"""The unified Farm Events store.

One append-only table, three clearly separated layers of data:

  * raw_payload  -> exactly what arrived, never mutated (audit / replay)
  * normalized   -> clean, queryable columns we define (event_time, type, ...)
  * derived tags -> things WE inferred (e.g. [BLOCKER], [SUCCESS])

Events are immutable. We never UPDATE a row in place, so there are no silent
overwrites: re-delivery of the same event is de-duplicated on `dedup_hash`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import JSON, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

# JSONB / ARRAY on Postgres; portable JSON on SQLite for zero-setup local runs.
JSONVariant = JSON().with_variant(JSONB(), "postgresql")
TagsVariant = JSON().with_variant(ARRAY(String), "postgresql")

# Bump when the normalization contract changes, so old rows stay interpretable.
SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FarmEvent(Base):
    __tablename__ = "farm_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # --- provenance ---
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # "webhook" | "sheet"
    source_event_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Idempotency key. Unique -> re-delivery is a no-op, never an overwrite.
    dedup_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # --- time: event_time (when it happened) vs received_at (when we ingested) ---
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # --- normalized fields ---
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    location: Mapped[str] = mapped_column(String(128), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # --- derived ---
    tags: Mapped[List[str]] = mapped_column(TagsVariant, nullable=False, default=list)

    # --- untouched original + structured normalized copy ---
    raw_payload: Mapped[Dict] = mapped_column(JSONVariant, nullable=False)
    normalized: Mapped[Dict] = mapped_column(JSONVariant, nullable=False)

    schema_version: Mapped[int] = mapped_column(default=SCHEMA_VERSION, nullable=False)

    __table_args__ = (
        UniqueConstraint("dedup_hash", name="uq_farm_events_dedup_hash"),
        Index("ix_farm_events_event_time", "event_time"),
        Index("ix_farm_events_type_time", "event_type", "event_time"),
        Index("ix_farm_events_location_time", "location", "event_time"),
    )
