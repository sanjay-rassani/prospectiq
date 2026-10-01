"""Application entry point.

One FastAPI service holds the API, the UI, and (from Phase 8) the scheduler. Spec
section 12 calls for a deliberately small runtime, so there is no separate worker process
and no message broker.
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.companies import router as companies_router
from app.api.opportunities import router as opportunities_router
from app.api.outreach import router as outreach_router
from app.config import get_settings
from app.db.session import get_session

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

app = FastAPI(
    title="Prospecting Engine",
    version="0.1.0",
    # No public API surface, so the docs endpoints are noise in production.
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.state.templates = templates

app.include_router(companies_router)
app.include_router(opportunities_router)
app.include_router(outreach_router)


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Liveness check that actually exercises the database.

    A health check that only confirms the process is running will report green while
    Postgres is down, which is the one failure that matters here: Postgres is the single
    source of truth (spec section 18).
    """
    try:
        session.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:
        logger.exception("health check: database unreachable")
        database = f"error: {type(exc).__name__}"

    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "env": settings.env,
    }


@app.get("/", response_class=HTMLResponse)
def today(request: Request) -> HTMLResponse:
    """The 'Today' screen (spec section 16). Populated in Phase 8; a placeholder until the
    pipeline has something to show."""
    return templates.TemplateResponse(
        request=request,
        name="today.html",
        context={"title": "Today"},
    )
