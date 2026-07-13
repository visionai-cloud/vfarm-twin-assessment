from __future__ import annotations

from datetime import datetime, timezone

from app.normalize import (
    compute_dedup_hash,
    normalize_event,
    normalize_location,
    normalize_type,
    parse_timestamp,
)

NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


def test_normalize_type_maps_synonyms():
    assert normalize_type("sensor") == "sensor_alert"
    assert normalize_type("Check-In") == "builder_update"
    assert normalize_type("  ENV ") == "environment"


def test_normalize_type_unknown_falls_back_to_other():
    assert normalize_type("wibble") == "other"
    assert normalize_type(None) == "other"


def test_normalize_location_slugifies():
    assert normalize_location("Pod A / Rack 3") == "pod-a-rack-3"
    assert normalize_location("  ") == "unknown"
    assert normalize_location(None) == "unknown"


def test_parse_timestamp_iso_with_z():
    dt = parse_timestamp("2026-07-14T09:40:00Z", fallback=NOW)
    assert dt == datetime(2026, 7, 14, 9, 40, tzinfo=timezone.utc)


def test_parse_timestamp_epoch_millis():
    dt = parse_timestamp(1752489600000, fallback=NOW)  # 2025-07-14T08:00:00Z-ish
    assert dt.tzinfo is not None


def test_parse_timestamp_bad_value_uses_fallback():
    assert parse_timestamp("not-a-date", fallback=NOW) == NOW
    assert parse_timestamp(None, fallback=NOW) == NOW


def test_dedup_hash_prefers_source_event_id_and_is_stable():
    a = compute_dedup_hash("webhook", "abc", {"type": "x"})
    b = compute_dedup_hash("webhook", "abc", {"type": "totally different"})
    assert a == b  # same id -> same hash regardless of body


def test_dedup_hash_content_hash_when_no_id():
    a = compute_dedup_hash("webhook", None, {"type": "x", "location": "pod-a"})
    b = compute_dedup_hash("webhook", None, {"location": "pod-a", "type": "x"})  # key order
    c = compute_dedup_hash("webhook", None, {"type": "y"})
    assert a == b  # order-independent
    assert a != c


def test_normalize_event_end_to_end():
    raw = {
        "type": "sensor",
        "timestamp": "2026-07-14T09:40:00Z",
        "location": "Pod B",
        "notes": "  pump blocked ",
        "source_event_id": "evt-1",
    }
    norm = normalize_event("webhook", raw, now=NOW)
    assert norm["event_type"] == "sensor_alert"
    assert norm["location"] == "pod-b"
    assert norm["notes"] == "pump blocked"
    assert norm["source_event_id"] == "evt-1"
    assert norm["event_time"] == datetime(2026, 7, 14, 9, 40, tzinfo=timezone.utc)
