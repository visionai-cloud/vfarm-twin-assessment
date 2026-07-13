from __future__ import annotations

from app.sources.sheet import parse_csv

CSV = """timestamp,type,location,notes,source_event_id
2026-07-14T08:15:00Z,builder,Pod A,healthy,bu-001

2026-07-14T09:40:00Z,builder,Pod B,pump blocked,
"""


def test_parse_csv_reads_rows_and_skips_blanks():
    rows = parse_csv(CSV)
    assert len(rows) == 2
    assert rows[0]["source_event_id"] == "bu-001"


def test_parse_csv_synthesises_id_when_missing():
    rows = parse_csv(CSV)
    # Second row had no id -> stable synthesised id from index + content.
    assert rows[1]["source_event_id"].startswith("row-")
    assert "Pod B" in rows[1]["source_event_id"]
