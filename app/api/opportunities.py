"""Opportunity detail and outreach-ready override routes."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from queue import Queue
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal, get_session
from app.models import (
    Company,
    InteractionOutcome,
    Opportunity,
    OpportunityEvidence,
    Person,
    ResearchTask,
    ResearchTaskStatus,
)
from app.services.buyers.research_links import research_search_links
from app.services.buyers.research_tasks import find_person_for_role
from app.services.contacts.discover import discover_contacts_for_company
from app.services.contacts.relevance import rank_contacts_for_opportunity
from app.services.contacts.scan_history import list_contact_scans, record_contact_scan
from app.services.scoring.promotion import override_outreach_ready

logger = logging.getLogger(__name__)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]

# Prevent EventSource auto-reconnect from starting a second concurrent scan.
_active_contact_scans: set[UUID] = set()
_active_contact_scans_lock = threading.Lock()


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
    refresh_scan = request.query_params.get("refresh", "") == "1"
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
            "finding": finding,
            "refresh_scan": refresh_scan,
            "has_contacts": has_contacts,
            "previous_scans": list_contact_scans(
                session, opportunity.company_id, limit=8
            ),
            "flash": request.query_params.get("flash"),
        },
    )


@router.post("/opportunities/{opportunity_id}/discover-contacts")
def opportunity_discover_contacts(
    session: SessionDep,
    opportunity_id: UUID,
    refresh: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Kick the loading UI; the SSE stream runs the actual scan with live logs."""
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return RedirectResponse(url="/companies?flash=Opportunity not found", status_code=303)
    refresh_q = "&refresh=1" if refresh == "1" else ""
    return RedirectResponse(
        url=(
            f"/opportunities/{opportunity_id}"
            f"?step=2&finding=1{refresh_q}"
            "&flash=Scanning company website for contacts…"
        ),
        status_code=303,
    )


def _people_count(session: Session, company_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Person)
            .where(Person.company_id == company_id, Person.archived_at.is_(None))
        )
        or 0
    )


@router.get("/opportunities/{opportunity_id}/discover-contacts/stream")
def opportunity_discover_contacts_stream(
    opportunity_id: UUID,
    refresh: Annotated[str, Query()] = "",
) -> StreamingResponse:
    """SSE: run contact discovery and stream one-line progress (where it is looking)."""
    q: Queue[dict[str, Any] | None] = Queue()
    do_refresh = refresh == "1"

    def worker() -> None:
        with _active_contact_scans_lock:
            if opportunity_id in _active_contact_scans:
                q.put(
                    {
                        "level": "warn",
                        "message": "A scan is already running for this opportunity…",
                        "status": "running",
                        "busy": True,
                    }
                )
                q.put(
                    {
                        "level": "done",
                        "message": "Already scanning — wait for the other tab/stream to finish.",
                        "status": "done",
                        "busy": False,
                        "done": True,
                        "people_count": 0,
                        "started_count": 0,
                    }
                )
                q.put(None)
                return
            _active_contact_scans.add(opportunity_id)

        session = SessionLocal()
        try:
            opportunity = session.get(Opportunity, opportunity_id)
            if opportunity is None:
                q.put(
                    {
                        "level": "error",
                        "message": "Opportunity not found",
                        "status": "missing",
                        "busy": False,
                        "done": True,
                    }
                )
                return
            company_id = opportunity.company_id
            started = _people_count(session, company_id)

            def on_progress(level: str, message: str) -> None:
                q.put(
                    {
                        "level": level,
                        "message": message,
                        "status": "running",
                        "busy": True,
                        "people_count": _people_count(session, company_id),
                        "started_count": started,
                    }
                )

            q.put(
                {
                    "level": "info",
                    "message": "Starting website contact scan…",
                    "status": "running",
                    "busy": True,
                    "people_count": started,
                    "started_count": started,
                }
            )
            result = discover_contacts_for_company(
                session,
                company_id,
                refresh=do_refresh,
                on_progress=on_progress,
            )
            record_contact_scan(
                session,
                company_id,
                result=result,
                outcome=result.message,
                ok=True,
                source="opportunity_stream",
            )
            session.commit()
            findings = list(result.findings)
            q.put(
                {
                    "level": "done",
                    "message": result.message,
                    "status": "done",
                    "busy": False,
                    "done": True,
                    "people_count": _people_count(session, company_id),
                    "started_count": started,
                    "created": result.people_created,
                    "enriched": result.people_enriched,
                    "findings": findings,
                }
            )
        except Exception as exc:
            session.rollback()
            logger.exception("contact discover stream failed")
            try:
                opportunity = session.get(Opportunity, opportunity_id)
                if opportunity is not None:
                    record_contact_scan(
                        session,
                        opportunity.company_id,
                        outcome=f"Scan failed: {exc}",
                        ok=False,
                        error=str(exc),
                        source="opportunity_stream",
                    )
                    session.commit()
            except Exception:  # noqa: BLE001
                session.rollback()
            q.put(
                {
                    "level": "error",
                    "message": f"Scan failed: {exc}",
                    "status": "failed",
                    "busy": False,
                    "done": True,
                }
            )
        finally:
            with _active_contact_scans_lock:
                _active_contact_scans.discard(opportunity_id)
            session.close()
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def events() -> Iterator[str]:
        while True:
            item = q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, default=str)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
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
