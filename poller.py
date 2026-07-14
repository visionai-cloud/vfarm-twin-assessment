"""Standalone Source B poller.

Runs outside the request cycle: every SHEET_POLL_SECONDS it pulls the builder
sheet and ingests new rows. Deliberately a plain loop (no APScheduler dep) —
in production this becomes a cron job or a Vercel Cron hitting POST /ingest/sheet.
"""
from __future__ import annotations

import time

from app.config import settings
from app.db import SessionLocal, init_db
from app.ingest import ingest_events
from app.log import get_logger, setup_logging
from app.sources.sheet import fetch_rows

logger = get_logger("poller")


def poll_once() -> dict:
    session = SessionLocal()
    try:
        rows = fetch_rows(settings.sheet_csv_url)
        return ingest_events(session, "sheet", rows)
    finally:
        session.close()


def main() -> None:
    setup_logging()
    init_db()
    logger.info("polling %s every %ss", settings.sheet_csv_url, settings.sheet_poll_seconds)
    while True:
        try:
            poll_once()
        except Exception:  # keep the loop alive on transient fetch errors
            logger.exception("poll failed")
        time.sleep(settings.sheet_poll_seconds)


if __name__ == "__main__":
    main()
