"""Failed jobs observability (P8-10)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.jobs.scheduler import scheduler_status
from app.models import Job, JobStatus

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/jobs/failed", response_class=HTMLResponse)
def failed_jobs(request: Request, session: SessionDep) -> HTMLResponse:
    templates = get_templates(request)
    failed = list(
        session.scalars(
            select(Job)
            .where(Job.status == JobStatus.FAILED.value)
            .order_by(Job.updated_at.desc())
            .limit(100)
        ).all()
    )
    running = list(
        session.scalars(
            select(Job)
            .where(Job.status == JobStatus.RUNNING.value)
            .order_by(Job.locked_at.desc().nullslast())
            .limit(20)
        ).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="jobs/failed.html",
        context={
            "title": "Failed jobs",
            "failed": failed,
            "running": running,
            "scheduler": scheduler_status(),
        },
    )
