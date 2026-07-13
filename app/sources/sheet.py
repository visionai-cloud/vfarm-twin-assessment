"""Source B: builder updates from a CSV (Google Sheet 'publish to web' CSV,
a remote URL, or a local file).

Parsing (bytes -> list[dict]) is pure and unit-testable; fetching is the only
I/O and is isolated in `fetch_rows`.
"""
from __future__ import annotations

import csv
import io

import httpx

# Sheet columns -> raw payload keys. Builders just fill in a spreadsheet.
EXPECTED_COLUMNS = ("timestamp", "type", "location", "notes", "source_event_id")


def parse_csv(text: str) -> list[dict]:
    """CSV text -> raw payload dicts (one per row). Blank rows skipped."""
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    for i, row in enumerate(reader):
        # Skip fully-empty rows.
        if not any((v or "").strip() for v in row.values()):
            continue
        payload = {k: (row.get(k) or "").strip() for k in EXPECTED_COLUMNS}
        # If the sheet has no id column, synthesise a stable one from row index
        # + content so re-polling the same row de-dupes instead of duplicating.
        if not payload.get("source_event_id"):
            payload["source_event_id"] = f"row-{i}:{payload['timestamp']}:{payload['location']}"
        rows.append(payload)
    return rows


def fetch_rows(url_or_path: str) -> list[dict]:
    """Fetch the sheet CSV from a URL or local path and parse it."""
    if url_or_path.startswith(("http://", "https://")):
        resp = httpx.get(url_or_path, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        text = resp.text
    else:
        with open(url_or_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    return parse_csv(text)
