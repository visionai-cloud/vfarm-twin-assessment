"""Build the 'Last 24 Hours in the Farm' summary.

`build_summary` is a pure function over a list of events + a window, so it is
unit-tested without a DB. `summary_last_24h` is the DB-querying wrapper: it
computes totals and groupings in SQL (accurate and scalable), and pulls only a
bounded set of events into memory for the blocker/success/experiment detail
lists — so the endpoint stays flat even with millions of events in the window.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .log import get_logger
from .models import FarmEvent

logger = get_logger(__name__)


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
    """Group + bucket events into the AI-narratable summary shape.

    Pure: everything is derived from `events`. `summary_last_24h` overrides the
    totals/groupings with SQL-accurate values when the detail set is bounded.
    """
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
        "truncated": False,
    }


def summary_last_24h(
    session: Session,
    *,
    now: datetime | None = None,
    hours: int = 24,
    detail_limit: int | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    limit = detail_limit or settings.summary_detail_limit
    window_start = now - timedelta(hours=hours)
    # Window on event_time (when it happened), not received_at, so backfilled
    # data lands in the right window.
    where = (FarmEvent.event_time >= window_start, FarmEvent.event_time <= now)

    # Accurate + scalable: counts and groupings computed in SQL (indexed columns).
    total = session.scalar(select(func.count()).select_from(FarmEvent).where(*where)) or 0
    by_type = dict(
        session.execute(
            select(FarmEvent.event_type, func.count()).where(*where).group_by(FarmEvent.event_type)
        ).all()
    )
    by_location = dict(
        session.execute(
            select(FarmEvent.location, func.count()).where(*where).group_by(FarmEvent.location)
        ).all()
    )

    # Bounded fetch for the detail buckets (most recent first).
    events = list(
        session.scalars(
            select(FarmEvent).where(*where).order_by(FarmEvent.event_time.desc()).limit(limit)
        ).all()
    )

    summary = build_summary(events, window_start, now)
    # Override with the SQL-accurate figures.
    summary["total_events"] = total
    summary["by_type"] = by_type
    summary["by_location"] = by_location
    summary["truncated"] = total > len(events)
    if summary["truncated"]:
        logger.warning(
            "summary truncated: %d events in window, detail buckets cover most recent %d",
            total,
            len(events),
        )
    return summary
