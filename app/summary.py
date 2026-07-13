"""Build the 'Last 24 Hours in the Farm' summary.

`build_summary` is a pure function over a list of events + a window, so it is
unit-tested without a DB. `summary_last_24h` is the thin DB-querying wrapper.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import FarmEvent


def _ref(event: FarmEvent) -> dict:
    return {
        "id": event.id,
        "event_time": event.event_time,
        "location": event.location,
        "event_type": event.event_type,
        "notes": event.notes,
        "tags": list(event.tags or []),
    }


def build_summary(events: list[FarmEvent], window_start: datetime, window_end: datetime) -> dict:
    """Group + bucket events into the AI-narratable summary shape."""
    by_type: Counter[str] = Counter()
    by_location: Counter[str] = Counter()
    blockers: list[dict] = []
    successes: list[dict] = []
    experiments: list[dict] = []

    for event in events:
        by_type[event.event_type] += 1
        by_location[event.location] += 1
        tags = set(event.tags or [])
        if "BLOCKER" in tags:
            blockers.append(_ref(event))
        if "SUCCESS" in tags:
            successes.append(_ref(event))
        if "EXPERIMENT" in tags:
            experiments.append(_ref(event))

    return {
        "window_start": window_start,
        "window_end": window_end,
        "total_events": len(events),
        "by_type": dict(by_type),
        "by_location": dict(by_location),
        "counts": {
            "blockers": len(blockers),
            "successes": len(successes),
            "experiments": len(experiments),
        },
        "blockers": blockers,
        "successes": successes,
        "experiments": experiments,
    }


def summary_last_24h(session: Session, *, now: datetime | None = None, hours: int = 24) -> dict:
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(hours=hours)
    # Window on event_time (when it happened), not received_at, so backfilled
    # data lands in the right window.
    events = list(
        session.scalars(
            select(FarmEvent)
            .where(FarmEvent.event_time >= window_start)
            .where(FarmEvent.event_time <= now)
            .order_by(FarmEvent.event_time.desc())
        ).all()
    )
    return build_summary(events, window_start, now)
