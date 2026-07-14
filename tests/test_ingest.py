from __future__ import annotations

from datetime import datetime, timezone

from app.db import SessionLocal, init_db
from app.ingest import ingest_events
from app.summary import summary_last_24h


def setup_module() -> None:
    init_db()


def _payload(**over):
    base = {
        "type": "sensor",
        "location": "Pod Z",
        "notes": "reading",
        "source_event_id": "ingest-default",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    base.update(over)
    return base


def test_service_level_idempotency_across_calls():
    session = SessionLocal()
    try:
        p = _payload(source_event_id="ingest-1")
        first = ingest_events(session, "webhook", [p])
        second = ingest_events(session, "webhook", [p])
        assert first["stored"] == 1
        assert second["stored"] == 0 and second["duplicates"] == 1
    finally:
        session.close()


def test_batch_internal_dedup():
    session = SessionLocal()
    try:
        p = _payload(source_event_id="ingest-batch")
        # Same event twice in one payload -> one stored, one duplicate.
        result = ingest_events(session, "webhook", [p, dict(p)])
        assert result["stored"] == 1 and result["duplicates"] == 1
    finally:
        session.close()


def test_summary_truncation_keeps_totals_accurate():
    session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        for i in range(3):
            ingest_events(
                session,
                "webhook",
                [_payload(type="builder", location=f"trunc-{i}",
                          notes="ok", source_event_id=f"trunc-{i}",
                          timestamp=now.isoformat())],
            )
        # Cap detail fetch at 1 -> must flag truncation but keep SQL totals right.
        summary = summary_last_24h(session, now=now, detail_limit=1)
        assert summary["truncated"] is True
        assert summary["total_events"] >= 3  # accurate count from SQL, not the cap
    finally:
        session.close()
