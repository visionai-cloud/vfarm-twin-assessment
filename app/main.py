"""FastAPI app: the webhook (Source A), a manual sheet-poll trigger (Source B),
and the 24h summary endpoint.
"""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import DEFAULT_WEBHOOK_TOKEN, settings
from .db import get_session, init_db
from .ingest import ingest_events
from .log import get_logger, setup_logging
from .narrate import narrate
from .schemas import IngestResult, NarrationResponse, SummaryResponse, WebhookEvent
from .sources.sheet import fetch_rows
from .summary import summary_last_24h

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    # Fail fast: never run production with the shipped placeholder token.
    if settings.environment == "production" and settings.webhook_token == DEFAULT_WEBHOOK_TOKEN:
        raise RuntimeError("WEBHOOK_TOKEN is still the default placeholder; set a real secret.")
    if settings.webhook_token == DEFAULT_WEBHOOK_TOKEN:
        logger.warning("WEBHOOK_TOKEN is the default placeholder — fine for dev, unsafe in prod.")
    init_db()
    logger.info("vFarm API started (env=%s)", settings.environment)
    yield


app = FastAPI(title="vFarm Event Ingestion + Summary", version="1.0.0", lifespan=lifespan)


def require_webhook_token(x_vfarm_token: Optional[str] = Header(default=None)) -> None:
    """Authenticate Source A. Webhooks are public URLs, so a shared secret is
    the minimum bar; swap for HMAC signature verification in production.

    Uses a constant-time compare to avoid leaking the token via response timing.
    """
    if x_vfarm_token is None or not secrets.compare_digest(
        x_vfarm_token, settings.webhook_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing webhook token"
        )


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    """Liveness + readiness: also verifies the DB is reachable."""
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health check: database unreachable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unreachable"
        )
    return {"status": "ok"}


@app.post("/ingest/webhook", response_model=IngestResult, dependencies=[Depends(require_webhook_token)])
def ingest_webhook(event: WebhookEvent, session: Session = Depends(get_session)) -> IngestResult:
    """Source A: a single farm event pushed as JSON."""
    result = ingest_events(session, "webhook", [event.model_dump()])
    return IngestResult(**result)


@app.post("/ingest/sheet", response_model=IngestResult)
def ingest_sheet(session: Session = Depends(get_session)) -> IngestResult:
    """Source B: pull the builder-updates sheet now and ingest new rows.

    Runs on a schedule via `poller.py`; this endpoint lets you trigger it
    on demand. Idempotent, so polling the same rows repeatedly is safe.
    """
    rows = fetch_rows(settings.sheet_csv_url)
    result = ingest_events(session, "sheet", rows)
    return IngestResult(**result)


@app.get("/summary/last-24h", response_model=SummaryResponse)
def summary(session: Session = Depends(get_session)) -> SummaryResponse:
    return SummaryResponse(**summary_last_24h(session))


@app.get("/summary/last-24h/narrate", response_model=NarrationResponse)
def summary_narrated(session: Session = Depends(get_session)) -> NarrationResponse:
    """The AI layer: turns the deterministic summary into prose an operator can
    read. Uses OpenAI when OPENAI_API_KEY is set, else a template fallback.
    """
    data = summary_last_24h(session)
    result = narrate(data)
    return NarrationResponse(summary=SummaryResponse(**data), **result)
