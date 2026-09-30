"""Opportunity detail and outreach-ready override routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_session
from app.models import Opportunity, OpportunityEvidence
from app.services.scoring.promotion import override_outreach_ready

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/opportunities/{opportunity_id}", response_class=HTMLResponse)
def opportunity_detail(
    request: Request,
    session: SessionDep,
    opportunity_id: UUID,
) -> HTMLResponse:
    templates = get_templates(request)
    opportunity = session.scalar(
        select(Opportunity)
        .where(Opportunity.id == opportunity_id)
        .options(
            selectinload(Opportunity.company),
            selectinload(Opportunity.evidence_links).selectinload(OpportunityEvidence.signal),
        )
    )
    if opportunity is None:
        return templates.TemplateResponse(
            request=request,
            name="opportunities/not_found.html",
            context={"title": "Not found"},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="opportunities/detail.html",
        context={
            "title": opportunity.title,
            "opportunity": opportunity,
            "flash": request.query_params.get("flash"),
        },
    )


@router.post("/opportunities/{opportunity_id}/override-outreach-ready")
def opportunity_override_outreach(
    session: SessionDep,
    opportunity_id: UUID,
    reason: Annotated[str, Form()],
) -> RedirectResponse:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return RedirectResponse(url="/companies?flash=Opportunity not found", status_code=303)
    try:
        override_outreach_ready(opportunity, reason)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/opportunities/{opportunity_id}?flash={exc}",
            status_code=303,
        )
    session.flush()
    return RedirectResponse(
        url=f"/opportunities/{opportunity_id}?flash=Marked outreach-ready by override",
        status_code=303,
    )
