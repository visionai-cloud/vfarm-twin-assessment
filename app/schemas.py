"""Pydantic request/response models for the API surface."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class WebhookEvent(BaseModel):
    """Source A payload. Extra keys are allowed and preserved in raw_payload."""

    model_config = ConfigDict(extra="allow")

    type: Optional[str] = None
    timestamp: Optional[Any] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    source_event_id: Optional[str] = None


class IngestResult(BaseModel):
    stored: int
    duplicates: int
    ids: list[str]


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    event_time: datetime
    received_at: datetime
    event_type: str
    location: str
    notes: str
    tags: list[str]


class EventRef(BaseModel):
    id: str
    event_time: datetime
    location: str
    event_type: str
    notes: str
    tags: list[str]


class SummaryResponse(BaseModel):
    """Shaped for an AI agent to read and narrate.

    Deliberately flat and labelled: counts for the skeleton, then the actual
    blocker/success/experiment events an agent would quote in narration.
    """

    window_start: datetime
    window_end: datetime
    total_events: int
    by_type: dict[str, int]
    by_location: dict[str, int]
    counts: dict[str, int] = Field(description="blockers / successes / experiments")
    blockers: list[EventRef]
    successes: list[EventRef]
    experiments: list[EventRef]
    truncated: bool = Field(
        default=False,
        description="True when the window held more events than the detail cap; "
        "totals/groupings stay accurate, detail lists cover the most recent events.",
    )


class NarrationResponse(BaseModel):
    """Human-readable narration of the 24h summary + provenance."""

    narration: str
    generated_by: str = Field(description='"openai" or "fallback"')
    model: Optional[str] = None
    note: Optional[str] = None
    summary: SummaryResponse
