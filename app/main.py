"""Application entry point.

One FastAPI service holds the API, the UI, and (from Phase 8) the scheduler. Spec
section 12 calls for a deliberately small runtime, so there is no separate worker process
and no message broker.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.companies import router as companies_router
from app.api.jobs import router as jobs_router
from app.api.opportunities import router as opportunities_router
from app.api.outreach import router as outreach_router
from app.config import get_settings
from app.db.session import get_session
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.services.monitoring.today import load_today

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(
    title="Prospecting Engine",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.state.templates = templates

app.include_router(companies_router)
app.include_router(opportunities_router)
app.include_router(outreach_router)
app.include_router(jobs_router)


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Liveness check that actually exercises the database."""
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("health check: database unreachable")
        database = f"error: {type(exc).__name__}"
    else:
        database = "ok"

    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "env": settings.env,
    }


@app.get("/", response_class=HTMLResponse)
def today(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """The 'Today' screen (spec section 16)."""
    payload = load_today(session)
    return templates.TemplateResponse(
        request=request,
        name="today.html",
        context={
            "title": "Today",
            "flash": request.query_params.get("flash"),
            **payload,
        },
    )
