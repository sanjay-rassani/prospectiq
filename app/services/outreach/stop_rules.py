"""Stop / nurture rules (spec §10.2 / P7-9). Deterministic only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    CompanyStatus,
    Interaction,
    InteractionDirection,
    InteractionOutcome,
    Opportunity,
    OpportunityStatus,
    Signal,
)
from app.services.outreach.lifecycle import transition_company, transition_opportunity
from app.services.scoring.profile import OperatorProfile, get_operator_profile


def apply_outcome_stop_rule(
    company: Company,
    opportunity: Opportunity,
    outcome: str,
) -> str | None:
    """Apply decline/irrelevant outcomes. Returns the action taken, or None."""
    if outcome == InteractionOutcome.DECLINED.value:
        transition_opportunity(opportunity, OpportunityStatus.NURTURE.value)
        if company.status not in {
            CompanyStatus.DISQUALIFIED.value,
            CompanyStatus.CLOSED.value,
            CompanyStatus.PROJECT_LEAD.value,
        }:
            transition_company(company, CompanyStatus.NURTURE.value)
        return "nurture:declined"
    if outcome == InteractionOutcome.IRRELEVANT.value:
        transition_opportunity(opportunity, OpportunityStatus.REJECTED.value)
        if company.status not in {
            CompanyStatus.CLOSED.value,
            CompanyStatus.PROJECT_LEAD.value,
        }:
            transition_company(company, CompanyStatus.DISQUALIFIED.value)
        return "disqualify:irrelevant"
    return None


def outbound_touch_count(session: Session, opportunity_id: object) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Interaction)
            .where(
                Interaction.opportunity_id == opportunity_id,
                Interaction.direction == InteractionDirection.OUTBOUND.value,
            )
        )
        or 0
    )


def has_inbound_reply(session: Session, opportunity_id: object) -> bool:
    return (
        session.scalar(
            select(Interaction.id)
            .where(
                Interaction.opportunity_id == opportunity_id,
                Interaction.direction == InteractionDirection.INBOUND.value,
            )
            .limit(1)
        )
        is not None
    )


def apply_unresponsive_rule(
    session: Session,
    company: Company,
    opportunity: Opportunity,
    *,
    profile: OperatorProfile | None = None,
) -> str | None:
    profile = profile or get_operator_profile()
    limit = profile.outreach.unresponsive_after_touches
    if has_inbound_reply(session, opportunity.id):
        return None
    if outbound_touch_count(session, opportunity.id) < limit:
        return None
    if opportunity.status in {
        OpportunityStatus.NURTURE.value,
        OpportunityStatus.CLOSED.value,
        OpportunityStatus.REJECTED.value,
        OpportunityStatus.PROJECT_LEAD.value,
    }:
        return None
    transition_opportunity(opportunity, OpportunityStatus.NURTURE.value)
    if company.status in {
        CompanyStatus.CONTACTED.value,
        CompanyStatus.QUALIFIED.value,
        CompanyStatus.RESEARCHED.value,
    }:
        transition_company(company, CompanyStatus.NURTURE.value)
    return f"nurture:unresponsive_after_{limit}"


def latest_signal_at(session: Session, company_id: object) -> datetime | None:
    return session.scalar(
        select(func.max(Signal.created_at)).where(Signal.company_id == company_id)
    )


def apply_stale_evidence_rule(
    session: Session,
    company: Company,
    opportunity: Opportunity,
    *,
    now: datetime | None = None,
    profile: OperatorProfile | None = None,
) -> str | None:
    profile = profile or get_operator_profile()
    now = now or datetime.now(UTC)
    latest = latest_signal_at(session, company.id)
    if latest is None:
        return None
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    age = now - latest
    if age < timedelta(days=profile.outreach.evidence_stale_days):
        return None
    if opportunity.status in {
        OpportunityStatus.CONTACTED.value,
        OpportunityStatus.REPLIED.value,
        OpportunityStatus.CONVERSATION.value,
        OpportunityStatus.PROJECT_LEAD.value,
        OpportunityStatus.CLOSED.value,
        OpportunityStatus.REJECTED.value,
    }:
        # Active conversations are not auto-watched for stale evidence.
        return None
    transition_opportunity(opportunity, OpportunityStatus.WATCH.value)
    if company.status in {
        CompanyStatus.QUALIFIED.value,
        CompanyStatus.RESEARCHED.value,
        CompanyStatus.NURTURE.value,
    }:
        transition_company(company, CompanyStatus.WATCH.value)
    return f"watch:evidence_stale_{profile.outreach.evidence_stale_days}d"
