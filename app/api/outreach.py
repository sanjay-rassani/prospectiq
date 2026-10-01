"""Outreach queue and task action routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db.session import get_session
from app.models import (
    Interaction,
    InteractionDirection,
    InteractionOutcome,
    Opportunity,
    OpportunityEvidence,
    OpportunityStatus,
    OutreachTask,
    OutreachTaskStatus,
)
from app.services.llm.gateway import OllamaGateway
from app.services.outreach.brief import brief_as_markdown
from app.services.outreach.interactions import record_interaction
from app.services.outreach.lifecycle import LifecycleError, transition_opportunity
from app.services.outreach.stop_rules import apply_stale_evidence_rule
from app.services.outreach.tasks import (
    approve_outreach,
    create_outreach_task,
    draft_outreach,
    mark_sent,
    reject_outreach,
    save_draft,
)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/outreach", response_class=HTMLResponse)
def outreach_queue(request: Request, session: SessionDep) -> HTMLResponse:
    templates = get_templates(request)
    now = datetime.now(UTC)
    awaiting = list(
        session.scalars(
            select(OutreachTask)
            .where(
                OutreachTask.status.in_(
                    [
                        OutreachTaskStatus.PENDING_DRAFT.value,
                        OutreachTaskStatus.DRAFT_READY.value,
                        OutreachTaskStatus.APPROVED.value,
                        OutreachTaskStatus.REJECTED.value,
                    ]
                )
            )
            .options(
                selectinload(OutreachTask.opportunity).selectinload(Opportunity.company),
                selectinload(OutreachTask.person),
            )
            .order_by(OutreachTask.due_at.asc().nullslast(), OutreachTask.created_at.desc())
        ).all()
    )
    due_followups = list(
        session.scalars(
            select(Interaction)
            .where(
                Interaction.next_action_at.is_not(None),
                Interaction.next_action_at <= now,
            )
            .options(
                selectinload(Interaction.opportunity).selectinload(Opportunity.company)
            )
            .order_by(Interaction.next_action_at.asc())
            .limit(50)
        ).all()
    )
    ready_without_task = list(
        session.scalars(
            select(Opportunity)
            .where(Opportunity.status == OpportunityStatus.OUTREACH_READY.value)
            .where(
                ~Opportunity.id.in_(
                    select(OutreachTask.opportunity_id).where(
                        OutreachTask.status.in_(
                            [
                                OutreachTaskStatus.PENDING_DRAFT.value,
                                OutreachTaskStatus.DRAFT_READY.value,
                                OutreachTaskStatus.APPROVED.value,
                                OutreachTaskStatus.SENT.value,
                            ]
                        )
                    )
                )
            )
            .options(selectinload(Opportunity.company))
            .order_by(Opportunity.opportunity_score.desc().nullslast())
            .limit(30)
        ).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="outreach/queue.html",
        context={
            "title": "Outreach",
            "awaiting": awaiting,
            "due_followups": due_followups,
            "ready_without_task": ready_without_task,
            "flash": request.query_params.get("flash"),
        },
    )


@router.get("/outreach/{task_id}", response_class=HTMLResponse)
def outreach_detail(
    request: Request,
    session: SessionDep,
    task_id: UUID,
) -> HTMLResponse:
    templates = get_templates(request)
    task = session.scalar(
        select(OutreachTask)
        .where(OutreachTask.id == task_id)
        .options(
            selectinload(OutreachTask.opportunity).selectinload(Opportunity.company),
            selectinload(OutreachTask.opportunity)
            .selectinload(Opportunity.evidence_links)
            .selectinload(OpportunityEvidence.signal),
            selectinload(OutreachTask.opportunity).selectinload(Opportunity.interactions),
            selectinload(OutreachTask.person),
        )
    )
    if task is None:
        return templates.TemplateResponse(
            request=request,
            name="outreach/not_found.html",
            context={"title": "Not found"},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="outreach/detail.html",
        context={
            "title": f"Outreach — {task.opportunity.title}",
            "task": task,
            "brief_md": brief_as_markdown(task.brief_json or {}),
            "outcomes": [o.value for o in InteractionOutcome],
            "flash": request.query_params.get("flash"),
        },
    )


@router.post("/opportunities/{opportunity_id}/outreach")
def start_outreach(
    session: SessionDep,
    opportunity_id: UUID,
    channel: Annotated[str, Form()] = "linkedin",
) -> RedirectResponse:
    opportunity = session.scalar(
        select(Opportunity)
        .where(Opportunity.id == opportunity_id)
        .options(selectinload(Opportunity.company))
    )
    if opportunity is None:
        return RedirectResponse(url="/outreach?flash=Opportunity not found", status_code=303)
    company = opportunity.company
    gateway = None
    if get_settings().llm_enabled:
        gateway = OllamaGateway()
    try:
        try:
            task = create_outreach_task(
                session, opportunity, company, channel=channel, gateway=gateway
            )
        finally:
            if gateway is not None:
                gateway.close()
    except ValueError as exc:
        return RedirectResponse(
            url=f"/opportunities/{opportunity_id}?flash={exc}",
            status_code=303,
        )
    return RedirectResponse(url=f"/outreach/{task.id}?flash=Brief created", status_code=303)


@router.post("/outreach/{task_id}/save-draft")
def outreach_save_draft(
    session: SessionDep,
    task_id: UUID,
    draft: Annotated[str, Form()],
) -> RedirectResponse:
    task = session.get(OutreachTask, task_id)
    if task is None:
        return RedirectResponse(url="/outreach?flash=Task not found", status_code=303)
    try:
        save_draft(task, draft)
    except ValueError as exc:
        return RedirectResponse(url=f"/outreach/{task_id}?flash={exc}", status_code=303)
    session.flush()
    return RedirectResponse(url=f"/outreach/{task_id}?flash=Draft saved", status_code=303)


@router.post("/outreach/{task_id}/generate-draft")
def outreach_generate_draft(
    session: SessionDep,
    task_id: UUID,
) -> RedirectResponse:
    task = session.get(OutreachTask, task_id)
    if task is None:
        return RedirectResponse(url="/outreach?flash=Task not found", status_code=303)
    if not get_settings().llm_enabled:
        return RedirectResponse(
            url=f"/outreach/{task_id}?flash=LLM disabled — write the draft manually",
            status_code=303,
        )
    with OllamaGateway() as gateway:
        draft_outreach(session, task, gateway=gateway)
    return RedirectResponse(
        url=f"/outreach/{task_id}?flash=Draft generated — review before approving",
        status_code=303,
    )


@router.post("/outreach/{task_id}/approve")
def outreach_approve(session: SessionDep, task_id: UUID) -> RedirectResponse:
    task = session.get(OutreachTask, task_id)
    if task is None:
        return RedirectResponse(url="/outreach?flash=Task not found", status_code=303)
    try:
        approve_outreach(task)
    except ValueError as exc:
        return RedirectResponse(url=f"/outreach/{task_id}?flash={exc}", status_code=303)
    session.flush()
    return RedirectResponse(
        url=f"/outreach/{task_id}?flash=Approved — send it yourself, then mark sent",
        status_code=303,
    )


@router.post("/outreach/{task_id}/reject")
def outreach_reject(
    session: SessionDep,
    task_id: UUID,
    reason: Annotated[str, Form()],
) -> RedirectResponse:
    task = session.get(OutreachTask, task_id)
    if task is None:
        return RedirectResponse(url="/outreach?flash=Task not found", status_code=303)
    try:
        reject_outreach(task, reason)
    except ValueError as exc:
        return RedirectResponse(url=f"/outreach/{task_id}?flash={exc}", status_code=303)
    session.flush()
    return RedirectResponse(url=f"/outreach/{task_id}?flash=Draft rejected", status_code=303)


@router.post("/outreach/{task_id}/mark-sent")
def outreach_mark_sent(session: SessionDep, task_id: UUID) -> RedirectResponse:
    task = session.scalar(
        select(OutreachTask)
        .where(OutreachTask.id == task_id)
        .options(selectinload(OutreachTask.opportunity).selectinload(Opportunity.company))
    )
    if task is None:
        return RedirectResponse(url="/outreach?flash=Task not found", status_code=303)
    try:
        mark_sent(session, task, task.opportunity.company, task.opportunity)
    except (ValueError, LifecycleError) as exc:
        return RedirectResponse(url=f"/outreach/{task_id}?flash={exc}", status_code=303)
    return RedirectResponse(
        url=f"/outreach/{task_id}?flash=Marked sent — follow-up is due",
        status_code=303,
    )


@router.post("/opportunities/{opportunity_id}/interactions")
def opportunity_add_interaction(
    session: SessionDep,
    opportunity_id: UUID,
    channel: Annotated[str, Form()],
    direction: Annotated[str, Form()],
    outcome: Annotated[str, Form()],
    summary: Annotated[str, Form()] = "",
    raw_text: Annotated[str, Form()] = "",
    next_action_note: Annotated[str, Form()] = "",
    next_action_at: Annotated[str, Form()] = "",
) -> RedirectResponse:
    opportunity = session.scalar(
        select(Opportunity)
        .where(Opportunity.id == opportunity_id)
        .options(selectinload(Opportunity.company))
    )
    if opportunity is None:
        return RedirectResponse(url="/outreach?flash=Opportunity not found", status_code=303)

    parsed_next: datetime | None = None
    if next_action_at.strip():
        try:
            parsed_next = datetime.fromisoformat(next_action_at.strip())
            if parsed_next.tzinfo is None:
                parsed_next = parsed_next.replace(tzinfo=UTC)
        except ValueError:
            return RedirectResponse(
                url=f"/opportunities/{opportunity_id}?flash=Invalid next_action_at",
                status_code=303,
            )

    gateway = None
    if get_settings().llm_enabled and direction == InteractionDirection.INBOUND.value:
        gateway = OllamaGateway()
    try:
        try:
            record_interaction(
                session,
                opportunity.company,
                opportunity,
                channel=channel,
                direction=direction,
                outcome=outcome,
                summary=summary,
                raw_text=raw_text or None,
                next_action_at=parsed_next,
                next_action_note=next_action_note or None,
                gateway=gateway,
            )
        finally:
            if gateway is not None:
                gateway.close()
    except (ValueError, LifecycleError) as exc:
        return RedirectResponse(
            url=f"/opportunities/{opportunity_id}?flash={exc}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/opportunities/{opportunity_id}?flash=Interaction recorded",
        status_code=303,
    )


@router.post("/opportunities/{opportunity_id}/lifecycle")
def opportunity_lifecycle(
    session: SessionDep,
    opportunity_id: UUID,
    status: Annotated[str, Form()],
) -> RedirectResponse:
    opportunity = session.scalar(
        select(Opportunity)
        .where(Opportunity.id == opportunity_id)
        .options(selectinload(Opportunity.company))
    )
    if opportunity is None:
        return RedirectResponse(url="/outreach?flash=Opportunity not found", status_code=303)
    try:
        transition_opportunity(opportunity, status)
    except LifecycleError as exc:
        return RedirectResponse(
            url=f"/opportunities/{opportunity_id}?flash={exc}",
            status_code=303,
        )
    session.flush()
    return RedirectResponse(
        url=f"/opportunities/{opportunity_id}?flash=Status → {status}",
        status_code=303,
    )


@router.post("/opportunities/{opportunity_id}/check-stale")
def opportunity_check_stale(
    session: SessionDep,
    opportunity_id: UUID,
) -> RedirectResponse:
    opportunity = session.scalar(
        select(Opportunity)
        .where(Opportunity.id == opportunity_id)
        .options(selectinload(Opportunity.company))
    )
    if opportunity is None:
        return RedirectResponse(url="/outreach?flash=Opportunity not found", status_code=303)
    action = apply_stale_evidence_rule(session, opportunity.company, opportunity)
    session.flush()
    flash = action or "Evidence still fresh — no change"
    return RedirectResponse(
        url=f"/opportunities/{opportunity_id}?flash={flash}",
        status_code=303,
    )
