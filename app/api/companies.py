"""Company list, seed, detail, and refresh routes."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_session
from app.models import Company, SourceSnapshot
from app.services.discovery.seed import refresh_company, seed_targets

logger = logging.getLogger(__name__)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/companies", response_class=HTMLResponse)
def companies_list(request: Request, session: SessionDep) -> HTMLResponse:
    templates = get_templates(request)
    companies = session.scalars(
        select(Company).order_by(Company.updated_at.desc())
    ).all()
    snapshot_counts = dict(
        session.execute(
            select(SourceSnapshot.company_id, func.count())
            .group_by(SourceSnapshot.company_id)
        ).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="companies/list.html",
        context={
            "title": "Companies",
            "companies": companies,
            "snapshot_counts": snapshot_counts,
            "flash": request.query_params.get("flash"),
        },
    )


@router.get("/companies/seed", response_class=HTMLResponse)
def seed_form(request: Request) -> HTMLResponse:
    templates = get_templates(request)
    return templates.TemplateResponse(
        request=request,
        name="companies/seed.html",
        context={"title": "Seed companies", "error": None, "blob": ""},
    )


@router.post("/companies/seed", response_class=HTMLResponse, response_model=None)
def seed_submit(
    request: Request,
    session: SessionDep,
    blob: Annotated[str, Form()],
) -> HTMLResponse | RedirectResponse:
    templates = get_templates(request)
    try:
        outcomes = seed_targets(session, blob)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="companies/seed.html",
            context={"title": "Seed companies", "error": str(exc), "blob": blob},
            status_code=400,
        )

    if not outcomes:
        return templates.TemplateResponse(
            request=request,
            name="companies/seed.html",
            context={
                "title": "Seed companies",
                "error": "No valid domains found. Enter one domain or URL per line.",
                "blob": blob,
            },
            status_code=400,
        )

    if len(outcomes) == 1:
        return RedirectResponse(
            url=f"/companies/{outcomes[0].company.id}?flash={outcomes[0].message}",
            status_code=303,
        )

    stored = sum(1 for o in outcomes if o.snapshot)
    return RedirectResponse(
        url=f"/companies?flash=Seeded {len(outcomes)} companies; {stored} new snapshots",
        status_code=303,
    )


@router.get("/companies/{company_id}", response_class=HTMLResponse)
def company_detail(
    request: Request,
    session: SessionDep,
    company_id: UUID,
) -> HTMLResponse:
    templates = get_templates(request)
    company = session.scalar(
        select(Company)
        .where(Company.id == company_id)
        .options(
            selectinload(Company.snapshots),
            selectinload(Company.signals),
            selectinload(Company.opportunities),
        )
    )
    if company is None:
        return templates.TemplateResponse(
            request=request,
            name="companies/not_found.html",
            context={"title": "Not found"},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="companies/detail.html",
        context={
            "title": company.name,
            "company": company,
            "flash": request.query_params.get("flash"),
        },
    )


@router.post("/companies/{company_id}/refresh")
def company_refresh(
    session: SessionDep,
    company_id: UUID,
) -> RedirectResponse:
    try:
        outcome = refresh_company(session, company_id)
    except LookupError:
        return RedirectResponse(url="/companies?flash=Company not found", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/companies/{company_id}?flash={exc}", status_code=303
        )
    return RedirectResponse(
        url=f"/companies/{company_id}?flash={outcome.message}",
        status_code=303,
    )
