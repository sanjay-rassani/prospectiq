"""Create, draft, approve, reject, and mark-sent for OutreachTask."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Company,
    CompanyStatus,
    Interaction,
    InteractionDirection,
    InteractionOutcome,
    Opportunity,
    OpportunityEvidence,
    OpportunityStatus,
    OutreachChannel,
    OutreachTask,
    OutreachTaskStatus,
    Person,
)
from app.services.buyers.research_tasks import find_person_for_role
from app.services.llm.gateway import CallResult, LlmGateway
from app.services.llm.schemas import OutreachDraft
from app.services.outreach.brief import assemble_brief, brief_as_markdown
from app.services.outreach.lifecycle import (
    ensure_company_qualified_for_outreach,
    transition_company,
    transition_opportunity,
)
from app.services.scoring.profile import get_operator_profile

logger = logging.getLogger(__name__)


def _load_opportunity_with_evidence(
    session: Session, opportunity_id: object
) -> Opportunity:
    return session.scalars(
        select(Opportunity)
        .where(Opportunity.id == opportunity_id)
        .options(
            selectinload(Opportunity.evidence_links).selectinload(OpportunityEvidence.signal)
        )
    ).one()


def create_outreach_task(
    session: Session,
    opportunity: Opportunity,
    company: Company,
    *,
    channel: str | None = None,
    person: Person | None = None,
    gateway: LlmGateway | None = None,
) -> OutreachTask:
    """Assemble brief (§10.1) and optionally draft (§10.2)."""
    if opportunity.status not in {
        OpportunityStatus.OUTREACH_READY.value,
        OpportunityStatus.ACTIVE.value,
    }:
        raise ValueError(
            f"Opportunity status {opportunity.status!r} cannot start outreach"
        )

    profile = get_operator_profile()
    channel = channel or profile.outreach.default_channel
    if channel not in {c.value for c in OutreachChannel}:
        raise ValueError(f"Unsupported channel: {channel}")

    if person is None and opportunity.buyer_role:
        people = list(
            session.scalars(select(Person).where(Person.company_id == company.id)).all()
        )
        person = find_person_for_role(people, opportunity.buyer_role)

    opportunity = _load_opportunity_with_evidence(session, opportunity.id)
    brief = assemble_brief(company, opportunity, person=person, channel=channel)
    due = datetime.now(UTC) + timedelta(days=profile.outreach.default_follow_up_days)
    task = OutreachTask(
        opportunity_id=opportunity.id,
        person_id=person.id if person else None,
        channel=channel,
        brief_json=brief,
        draft=None,
        status=OutreachTaskStatus.PENDING_DRAFT.value,
        due_at=due,
    )
    session.add(task)
    session.flush()

    if opportunity.status == OpportunityStatus.ACTIVE.value:
        transition_opportunity(opportunity, OpportunityStatus.OUTREACH_READY.value)
    ensure_company_qualified_for_outreach(company)

    if gateway is not None:
        draft_outreach(session, task, gateway=gateway)
    session.flush()
    return task


def draft_outreach(
    session: Session,
    task: OutreachTask,
    *,
    gateway: LlmGateway,
) -> CallResult:
    """Generate a draft constrained by §10.2. Operator must still approve."""
    from app.services.llm.facts import persist_llm_call

    brief_md = brief_as_markdown(task.brief_json or {})
    result = gateway.draft_outreach(brief_markdown=brief_md, channel=task.channel)
    opportunity = session.get(Opportunity, task.opportunity_id)
    company_id = opportunity.company_id if opportunity else None
    persist_llm_call(
        session,
        result,
        company_id=company_id,
        snapshot_id=opportunity.triggering_snapshot_id if opportunity else None,
    )
    if result.ok and isinstance(result.parsed, OutreachDraft):
        task.draft = result.parsed.body.strip()
        task.status = OutreachTaskStatus.DRAFT_READY.value
    else:
        logger.warning("draft_outreach failed: %s", result.errors)
    session.flush()
    return result


def save_draft(task: OutreachTask, draft: str) -> None:
    text = draft.strip()
    if not text:
        raise ValueError("Draft cannot be empty")
    task.draft = text
    if task.status in {
        OutreachTaskStatus.PENDING_DRAFT.value,
        OutreachTaskStatus.REJECTED.value,
    }:
        task.status = OutreachTaskStatus.DRAFT_READY.value


def approve_outreach(task: OutreachTask) -> None:
    """Operator-only approval (P7-4). Does not send."""
    if not (task.draft and task.draft.strip()):
        raise ValueError("Cannot approve an empty draft")
    if task.status not in {
        OutreachTaskStatus.DRAFT_READY.value,
        OutreachTaskStatus.REJECTED.value,
    }:
        raise ValueError(f"Cannot approve task in status {task.status!r}")
    task.status = OutreachTaskStatus.APPROVED.value
    task.approved_at = datetime.now(UTC)
    task.rejection_reason = None


def reject_outreach(task: OutreachTask, reason: str) -> None:
    reason = reason.strip()
    if not reason:
        raise ValueError("Rejection reason is required")
    if task.status not in {
        OutreachTaskStatus.DRAFT_READY.value,
        OutreachTaskStatus.APPROVED.value,
        OutreachTaskStatus.PENDING_DRAFT.value,
    }:
        raise ValueError(f"Cannot reject task in status {task.status!r}")
    task.status = OutreachTaskStatus.REJECTED.value
    task.rejection_reason = reason
    task.approved_at = None


def _advance_company_to_contacted(company: Company) -> None:
    if company.status == CompanyStatus.CONTACTED.value:
        return
    if company.status == CompanyStatus.SEEDED.value:
        transition_company(company, CompanyStatus.RESEARCHED.value)
    if company.status == CompanyStatus.RESEARCHED.value:
        ensure_company_qualified_for_outreach(company)
    if company.status in {
        CompanyStatus.QUALIFIED.value,
        CompanyStatus.WATCH.value,
        CompanyStatus.NURTURE.value,
    }:
        transition_company(company, CompanyStatus.CONTACTED.value)


def mark_sent(
    session: Session,
    task: OutreachTask,
    company: Company,
    opportunity: Opportunity,
    *,
    occurred_at: datetime | None = None,
    note: str | None = None,
) -> Interaction:
    """Record that the operator sent the message (human-operated)."""
    if task.status != OutreachTaskStatus.APPROVED.value:
        raise ValueError("Only approved drafts can be marked sent")
    when = occurred_at or datetime.now(UTC)
    task.status = OutreachTaskStatus.SENT.value
    interaction = Interaction(
        opportunity_id=opportunity.id,
        person_id=task.person_id,
        outreach_task_id=task.id,
        channel=task.channel,
        direction=InteractionDirection.OUTBOUND.value,
        occurred_at=when,
        summary=note or "Outreach sent by operator",
        raw_text=task.draft,
        outcome=InteractionOutcome.SENT.value,
        next_action_at=datetime.now(UTC)
        + timedelta(days=get_operator_profile().outreach.default_follow_up_days),
        next_action_note="Follow up if no reply",
    )
    session.add(interaction)
    transition_opportunity(opportunity, OpportunityStatus.CONTACTED.value)
    _advance_company_to_contacted(company)
    session.flush()
    return interaction
