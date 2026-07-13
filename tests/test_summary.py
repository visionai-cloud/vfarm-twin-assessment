from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import FarmEvent
from app.summary import build_summary

NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


def _event(event_type, location, tags, minutes_ago=10):
    return FarmEvent(
        id=f"id-{location}-{event_type}-{minutes_ago}",
        source="test",
        source_event_id=None,
        dedup_hash=f"h-{location}-{event_type}-{minutes_ago}",
        event_time=NOW - timedelta(minutes=minutes_ago),
        received_at=NOW,
        event_type=event_type,
        location=location,
        notes="",
        tags=tags,
        raw_payload={},
        normalized={},
    )


def test_build_summary_groups_and_buckets():
    events = [
        _event("builder_update", "pod-a", ["SUCCESS"]),
        _event("builder_update", "pod-b", ["BLOCKER"]),
        _event("experiment", "pod-c", ["EXPERIMENT"]),
        _event("sensor_alert", "pod-b", ["ALERT", "BLOCKER"]),
    ]
    summary = build_summary(events, NOW - timedelta(hours=24), NOW)

    assert summary["total_events"] == 4
    assert summary["by_type"]["builder_update"] == 2
    assert summary["by_location"]["pod-b"] == 2
    assert summary["counts"] == {"blockers": 2, "successes": 1, "experiments": 1}
    assert {b["location"] for b in summary["blockers"]} == {"pod-b"}
    assert summary["experiments"][0]["event_type"] == "experiment"


def test_build_summary_empty():
    summary = build_summary([], NOW - timedelta(hours=24), NOW)
    assert summary["total_events"] == 0
    assert summary["by_type"] == {}
    assert summary["counts"] == {"blockers": 0, "successes": 0, "experiments": 0}
