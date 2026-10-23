"""Contacts directory, detail, edit, and discovery job routes."""

from __future__ import annotations

import contextlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_session
from app.jobs.queue import enqueue_job
from app.models import Company, JobType, Person
from app.models.person import FieldEvidenceStatus
from app.services.contacts.discover import delete_or_archive_contact
from app.services.contacts.merge import apply_manual_fields
from app.services.contacts.relevance import rank_contacts_for_opportunity

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/contacts", response_class=HTMLResponse)
def contacts_list(
    request: Request,
    session: SessionDep,
    q: Annotated[str, Query()] = "",
    company_id: Annotated[str, Query()] = "",
    has_email: Annotated[str, Query()] = "",
    has_profile: Annotated[str, Query()] = "",
    seniority: Annotated[str, Query()] = "",
    status: Annotated[str, Query()] = "",
    page: Annotated[int, Query(ge=1)] = 1,
) -> HTMLResponse:
    templates = get_templates(request)
    page_size = 50
    stmt = (
        select(Person)
        .join(Company, Person.company_id == Company.id)
        .where(Person.archived_at.is_(None))
        .options(selectinload(Person.company))
        .order_by(Person.name.asc())
    )
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Person.name.ilike(like),
                Person.role.ilike(like),
                Person.department.ilike(like),
                Person.public_email.ilike(like),
                Company.name.ilike(like),
            )
        )
    if company_id.strip():
        with contextlib.suppress(ValueError):
            stmt = stmt.where(Person.company_id == UUID(company_id.strip()))
    if has_email == "1":
        stmt = stmt.where(Person.public_email.is_not(None))
    elif has_email == "0":
        stmt = stmt.where(Person.public_email.is_(None))
    if has_profile == "1":
        stmt = stmt.where(Person.public_profile_url.is_not(None))
    elif has_profile == "0":
        stmt = stmt.where(Person.public_profile_url.is_(None))
    if seniority.strip():
        stmt = stmt.where(Person.seniority == seniority.strip())
    if status.strip():
        stmt = stmt.where(Person.discovery_status == status.strip())

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    people = list(
        session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    )
    companies = list(
        session.scalars(select(Company).order_by(Company.name.asc()).limit(500)).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="contacts/list.html",
        context={
            "title": "Contacts",
            "active": "contacts",
            "people": people,
            "companies": companies,
            "total": total,
            "page": page,
            "page_size": page_size,
            "q": q,
            "company_id": company_id,
            "has_email": has_email,
            "has_profile": has_profile,
            "seniority": seniority,
            "status": status,
            "flash": request.query_params.get("flash"),
        },
    )


@router.get("/contacts/{person_id}", response_class=HTMLResponse)
def contact_detail(
    request: Request,
    session: SessionDep,
    person_id: UUID,
) -> HTMLResponse:
    templates = get_templates(request)
    person = session.scalar(
        select(Person)
        .where(Person.id == person_id)
        .options(selectinload(Person.company).selectinload(Company.opportunities))
    )
    if person is None:
        return templates.TemplateResponse(
            request=request,
            name="contacts/not_found.html",
            context={"title": "Not found", "active": "contacts"},
            status_code=404,
        )
    ranked: list = []
    for opp in person.company.opportunities[:10]:
        for item in rank_contacts_for_opportunity(
            session, opp, company=person.company, limit=50
        ):
            if item.person.id == person.id:
                ranked.append((opp, item))
                break
    return templates.TemplateResponse(
        request=request,
        name="contacts/detail.html",
        context={
            "title": person.name,
            "active": "contacts",
            "person": person,
            "ranked_opportunities": ranked,
            "email_statuses": [s.value for s in FieldEvidenceStatus],
            "flash": request.query_params.get("flash"),
        },
    )


@router.post("/contacts/{person_id}/edit")
def contact_edit(
    session: SessionDep,
    person_id: UUID,
    name: Annotated[str, Form()],
    role: Annotated[str, Form()],
    department: Annotated[str, Form()] = "",
    seniority: Annotated[str, Form()] = "",
    public_email: Annotated[str, Form()] = "",
    public_phone: Annotated[str, Form()] = "",
    public_profile_url: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    mark_email_verified: Annotated[str, Form()] = "",
    mark_profile_verified: Annotated[str, Form()] = "",
) -> RedirectResponse:
    person = session.get(Person, person_id)
    if person is None:
        return RedirectResponse(url="/contacts?flash=Contact not found", status_code=303)
    apply_manual_fields(
        person,
        name=name,
        role=role,
        department=department or None,
        seniority=seniority or None,
        public_email=public_email or None,
        public_phone=public_phone or None,
        public_profile_url=public_profile_url or None,
        notes=notes,
        mark_email_verified=mark_email_verified == "1",
        mark_profile_verified=mark_profile_verified == "1",
    )
    session.flush()
    return RedirectResponse(
        url=f"/contacts/{person_id}?flash=Contact updated",
        status_code=303,
    )


@router.post("/contacts/{person_id}/archive")
def contact_archive(session: SessionDep, person_id: UUID) -> RedirectResponse:
    try:
        delete_or_archive_contact(session, person_id, hard_delete=False)
    except LookupError:
        return RedirectResponse(url="/contacts?flash=Contact not found", status_code=303)
    return RedirectResponse(url="/contacts?flash=Contact archived", status_code=303)


@router.post("/contacts/{person_id}/delete")
def contact_delete(session: SessionDep, person_id: UUID) -> RedirectResponse:
    company_id = None
    person = session.get(Person, person_id)
    if person:
        company_id = person.company_id
    try:
        delete_or_archive_contact(session, person_id, hard_delete=True)
    except LookupError:
        return RedirectResponse(url="/contacts?flash=Contact not found", status_code=303)
    if company_id:
        return RedirectResponse(
            url=f"/companies/{company_id}?flash=Contact deleted",
            status_code=303,
        )
    return RedirectResponse(url="/contacts?flash=Contact deleted", status_code=303)


@router.post("/contacts/{person_id}/enrich")
def contact_enrich(session: SessionDep, person_id: UUID) -> RedirectResponse:
    person = session.get(Person, person_id)
    if person is None:
        return RedirectResponse(url="/contacts?flash=Contact not found", status_code=303)
    enqueue_job(
        session,
        JobType.DISCOVER_CONTACTS.value,
        entity_id=person.company_id,
        payload={"refresh": True, "person_id": str(person_id)},
        dedupe_pending=True,
    )
    return RedirectResponse(
        url=f"/contacts/{person_id}?flash=Enrichment job queued",
        status_code=303,
    )


@router.post("/companies/{company_id}/discover-contacts")
def company_discover_contacts(
    session: SessionDep,
    company_id: UUID,
    refresh: Annotated[str, Form()] = "",
    return_to: Annotated[str, Form()] = "",
) -> RedirectResponse:
    company = session.get(Company, company_id)
    if company is None:
        return RedirectResponse(url="/companies?flash=Company not found", status_code=303)
    enqueue_job(
        session,
        JobType.DISCOVER_CONTACTS.value,
        entity_id=company.id,
        payload={"refresh": refresh == "1"},
        dedupe_pending=True,
    )
    dest = return_to.strip()
    if dest.startswith("/opportunities/"):
        sep = "&" if "?" in dest else "?"
        return RedirectResponse(
            url=f"{dest}{sep}finding=1&flash=Scanning company website for contacts…",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/companies/{company_id}?flash=Contact discovery queued",
        status_code=303,
    )

