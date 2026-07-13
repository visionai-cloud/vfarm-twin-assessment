from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

client = TestClient(app)


def setup_module() -> None:
    init_db()


def _payload(**over):
    base = {
        "type": "sensor",
        "timestamp": "2026-07-14T11:59:00Z",
        "location": "Pod B",
        "notes": "pump blocked, waiting on part",
        "source_event_id": "evt-api-1",
    }
    base.update(over)
    return base


def test_webhook_denied_without_token():
    r = client.post("/ingest/webhook", json=_payload())
    assert r.status_code == 401


def test_webhook_denied_with_wrong_token():
    r = client.post("/ingest/webhook", json=_payload(), headers={"X-VFarm-Token": "nope"})
    assert r.status_code == 401


def test_webhook_allowed_and_stores():
    r = client.post(
        "/ingest/webhook", json=_payload(), headers={"X-VFarm-Token": "test-token"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["stored"] == 1
    assert body["duplicates"] == 0


def test_webhook_idempotent_no_silent_overwrite():
    # Re-deliver the same event id -> stored 0, counted as duplicate, not overwritten.
    p = _payload(source_event_id="evt-dupe", notes="original")
    h = {"X-VFarm-Token": "test-token"}
    first = client.post("/ingest/webhook", json=p, headers=h).json()
    second = client.post(
        "/ingest/webhook", json={**p, "notes": "TAMPERED"}, headers=h
    ).json()
    assert first["stored"] == 1
    assert second["stored"] == 0 and second["duplicates"] == 1


def test_sheet_ingest_is_idempotent():
    first = client.post("/ingest/sheet").json()
    second = client.post("/ingest/sheet").json()
    assert first["stored"] >= 1
    # Re-polling the same sheet stores nothing new.
    assert second["stored"] == 0


def test_summary_last_24h_buckets_recent_events():
    # Post a fresh blocker with a "now" timestamp so it always lands in-window,
    # independent of the machine date.
    now = datetime.now(timezone.utc).isoformat()
    client.post(
        "/ingest/webhook",
        json=_payload(
            source_event_id="evt-summary-blocker",
            timestamp=now,
            notes="Nutrient pump blocked, waiting on part",
        ),
        headers={"X-VFarm-Token": "test-token"},
    )

    s = client.get("/summary/last-24h")
    assert s.status_code == 200
    summary = s.json()
    assert summary["total_events"] >= 1
    assert "by_type" in summary and "blockers" in summary
    assert summary["counts"]["blockers"] >= 1
