"""Opportunity detail and outreach-ready override routes."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_session
from app.jobs.queue import enqueue_job
from app.models import (
    Company,
    InteractionOutcome,
    Job,
    JobStatus,
    JobType,
    Opportunity,
    OpportunityEvidence,
    Person,
    ResearchTask,
    ResearchTaskStatus,
)
from app.services.buyers.research_links import research_search_links
from app.services.buyers.research_tasks import find_person_for_role
from app.services.contacts.relevance import rank_contacts_for_opportunity
from app.services.scoring.promotion import override_outreach_ready

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _active_people(company: Company) -> list[Person]:
    return [p for p in company.people if p.archived_at is None]


def _default_step(
    *,
    has_contacts: bool,
    has_outreach: bool,
    has_interactions: bool,
    open_research: bool,
) -> int:
    if has_interactions:
        return 4
    if has_outreach:
        return 3
    if not has_contacts or open_research:
        return 2
    return 1


def _discovery_job_status(session: Session, company_id: UUID) -> dict[str, Any]:
    job = session.scalar(
        select(Job)
        .where(
            Job.entity_id == company_id,
            Job.job_type == JobType.DISCOVER_CONTACTS.value,
            Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if job is not None:
        return {"status": job.status, "busy": True, "job_id": str(job.id)}
    latest = session.scalar(
        select(Job)
        .where(
            Job.entity_id == company_id,
            Job.job_type == JobType.DISCOVER_CONTACTS.value,
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if latest is None:
        return {"status": "idle", "busy": False, "job_id": None}
    return {
        "status": latest.status,
        "busy": False,
        "job_id": str(latest.id),
        "error": latest.last_error,
    }


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
            selectinload(Opportunity.company).selectinload(Company.people),
            selectinload(Opportunity.evidence_links).selectinload(OpportunityEvidence.signal),
            selectinload(Opportunity.research_tasks),
            selectinload(Opportunity.outreach_tasks),
            selectinload(Opportunity.interactions),
        )
    )
    if opportunity is None:
        return templates.TemplateResponse(
            request=request,
            name="opportunities/not_found.html",
            context={"title": "Not found"},
            status_code=404,
        )
    people = _active_people(opportunity.company)
    matching_people = []
    if opportunity.buyer_role:
        match = find_person_for_role(people, opportunity.buyer_role)
        matching_people = [match] if match else []
    ranked_contacts = rank_contacts_for_opportunity(
        session, opportunity, company=opportunity.company, limit=15
    )
    open_tasks = [
        t for t in opportunity.research_tasks if t.status == ResearchTaskStatus.OPEN.value
    ]
    has_contacts = bool(ranked_contacts or matching_people or people)
    has_outreach = bool(opportunity.outreach_tasks)
    has_interactions = bool(opportunity.interactions)
    step_param = request.query_params.get("step", "").strip()
    try:
        step = int(step_param) if step_param else 0
    except ValueError:
        step = 0
    if step < 1 or step > 5:
        step = _default_step(
            has_contacts=has_contacts,
            has_outreach=has_outreach,
            has_interactions=has_interactions,
            open_research=bool(open_tasks),
        )
    finding = request.query_params.get("finding", "") == "1"
    discovery = _discovery_job_status(session, opportunity.company_id)
    return templates.TemplateResponse(
        request=request,
        name="opportunities/detail.html",
        context={
            "title": opportunity.title,
            "opportunity": opportunity,
            "matching_people": matching_people,
            "ranked_contacts": ranked_contacts,
            "company_people": people,
            "open_research_tasks": open_tasks,
            "outreach_tasks": opportunity.outreach_tasks,
            "interaction_outcomes": [o.value for o in InteractionOutcome],
            "research_links": research_search_links(
                opportunity.company, opportunity.buyer_role
            ),
            "step": step,
            "finding": finding or discovery["busy"],
            "discovery_status": discovery,
            "has_contacts": has_contacts,
            "flash": request.query_params.get("flash"),
        },
    )


@router.post("/opportunities/{opportunity_id}/discover-contacts")
def opportunity_discover_contacts(
    session: SessionDep,
    opportunity_id: UUID,
    refresh: Annotated[str, Form()] = "",
) -> RedirectResponse:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return RedirectResponse(url="/companies?flash=Opportunity not found", status_code=303)
    enqueue_job(
        session,
        JobType.DISCOVER_CONTACTS.value,
        entity_id=opportunity.company_id,
        payload={"refresh": refresh == "1"},
        dedupe_pending=True,
    )
    return RedirectResponse(
        url=(
            f"/opportunities/{opportunity_id}"
            "?step=2&finding=1&flash=Scanning company website for contacts…"
        ),
        status_code=303,
    )


@router.get("/opportunities/{opportunity_id}/discover-contacts/status")
def opportunity_discover_contacts_status(
    session: SessionDep,
    opportunity_id: UUID,
) -> JSONResponse:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return JSONResponse({"status": "missing", "busy": False}, status_code=404)
    people_count = len(
        [
            p
            for p in session.scalars(
                select(Person).where(
                    Person.company_id == opportunity.company_id,
                    Person.archived_at.is_(None),
                )
            ).all()
        ]
    )
    payload = _discovery_job_status(session, opportunity.company_id)
    payload["people_count"] = people_count
    return JSONResponse(payload)


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


@router.post("/research-tasks/{task_id}/done")
def research_task_done(
    session: SessionDep,
    task_id: UUID,
) -> RedirectResponse:
    task = session.get(ResearchTask, task_id)
    if task is None:
        return RedirectResponse(url="/companies?flash=Research task not found", status_code=303)
    task.status = ResearchTaskStatus.DONE.value
    session.flush()
    return RedirectResponse(
        url=f"/opportunities/{task.opportunity_id}?flash=Research task marked done",
        status_code=303,
    )
