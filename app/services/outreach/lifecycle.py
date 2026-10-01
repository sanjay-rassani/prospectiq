"""Deterministic company/opportunity lifecycle transitions (spec §10.3 / §15.2).

Model output never mutates lifecycle. Only these functions do.
"""

from __future__ import annotations

from app.models import Company, CompanyStatus, Opportunity, OpportunityStatus

# Spec §10.3 forward path plus side states. Keys are current status values.
_COMPANY_TRANSITIONS: dict[str, frozenset[str]] = {
    CompanyStatus.SEEDED.value: frozenset(
        {
            CompanyStatus.RESEARCHED.value,
            CompanyStatus.DISQUALIFIED.value,
            CompanyStatus.CLOSED.value,
            CompanyStatus.WATCH.value,
        }
    ),
    CompanyStatus.RESEARCHED.value: frozenset(
        {
            CompanyStatus.QUALIFIED.value,
            CompanyStatus.WATCH.value,
            CompanyStatus.NURTURE.value,
            CompanyStatus.DISQUALIFIED.value,
            CompanyStatus.CLOSED.value,
        }
    ),
    CompanyStatus.QUALIFIED.value: frozenset(
        {
            CompanyStatus.CONTACTED.value,
            CompanyStatus.WATCH.value,
            CompanyStatus.NURTURE.value,
            CompanyStatus.DISQUALIFIED.value,
            CompanyStatus.CLOSED.value,
        }
    ),
    CompanyStatus.CONTACTED.value: frozenset(
        {
            CompanyStatus.REPLIED.value,
            CompanyStatus.NURTURE.value,
            CompanyStatus.WATCH.value,
            CompanyStatus.DISQUALIFIED.value,
            CompanyStatus.CLOSED.value,
        }
    ),
    CompanyStatus.REPLIED.value: frozenset(
        {
            CompanyStatus.CONVERSATION.value,
            CompanyStatus.NURTURE.value,
            CompanyStatus.WATCH.value,
            CompanyStatus.DISQUALIFIED.value,
            CompanyStatus.CLOSED.value,
            CompanyStatus.PROJECT_LEAD.value,
        }
    ),
    CompanyStatus.CONVERSATION.value: frozenset(
        {
            CompanyStatus.PROJECT_LEAD.value,
            CompanyStatus.NURTURE.value,
            CompanyStatus.WATCH.value,
            CompanyStatus.DISQUALIFIED.value,
            CompanyStatus.CLOSED.value,
        }
    ),
    CompanyStatus.PROJECT_LEAD.value: frozenset(
        {
            CompanyStatus.CLOSED.value,
            CompanyStatus.NURTURE.value,
        }
    ),
    CompanyStatus.WATCH.value: frozenset(
        {
            CompanyStatus.RESEARCHED.value,
            CompanyStatus.QUALIFIED.value,
            CompanyStatus.NURTURE.value,
            CompanyStatus.DISQUALIFIED.value,
            CompanyStatus.CLOSED.value,
            CompanyStatus.CONTACTED.value,
        }
    ),
    CompanyStatus.NURTURE.value: frozenset(
        {
            CompanyStatus.WATCH.value,
            CompanyStatus.QUALIFIED.value,
            CompanyStatus.CONTACTED.value,
            CompanyStatus.DISQUALIFIED.value,
            CompanyStatus.CLOSED.value,
        }
    ),
    CompanyStatus.DISQUALIFIED.value: frozenset({CompanyStatus.CLOSED.value}),
    CompanyStatus.CLOSED.value: frozenset(),
}

_OPPORTUNITY_TRANSITIONS: dict[str, frozenset[str]] = {
    OpportunityStatus.ACTIVE.value: frozenset(
        {
            OpportunityStatus.OUTREACH_READY.value,
            OpportunityStatus.SUPERSEDED.value,
            OpportunityStatus.REJECTED.value,
            OpportunityStatus.WATCH.value,
            OpportunityStatus.NURTURE.value,
            OpportunityStatus.CLOSED.value,
        }
    ),
    OpportunityStatus.OUTREACH_READY.value: frozenset(
        {
            OpportunityStatus.CONTACTED.value,
            OpportunityStatus.SUPERSEDED.value,
            OpportunityStatus.REJECTED.value,
            OpportunityStatus.WATCH.value,
            OpportunityStatus.NURTURE.value,
            OpportunityStatus.CLOSED.value,
            OpportunityStatus.ACTIVE.value,
        }
    ),
    OpportunityStatus.CONTACTED.value: frozenset(
        {
            OpportunityStatus.REPLIED.value,
            OpportunityStatus.NURTURE.value,
            OpportunityStatus.WATCH.value,
            OpportunityStatus.REJECTED.value,
            OpportunityStatus.CLOSED.value,
        }
    ),
    OpportunityStatus.REPLIED.value: frozenset(
        {
            OpportunityStatus.CONVERSATION.value,
            OpportunityStatus.PROJECT_LEAD.value,
            OpportunityStatus.NURTURE.value,
            OpportunityStatus.WATCH.value,
            OpportunityStatus.REJECTED.value,
            OpportunityStatus.CLOSED.value,
        }
    ),
    OpportunityStatus.CONVERSATION.value: frozenset(
        {
            OpportunityStatus.PROJECT_LEAD.value,
            OpportunityStatus.NURTURE.value,
            OpportunityStatus.WATCH.value,
            OpportunityStatus.CLOSED.value,
        }
    ),
    OpportunityStatus.PROJECT_LEAD.value: frozenset(
        {
            OpportunityStatus.CLOSED.value,
            OpportunityStatus.NURTURE.value,
        }
    ),
    OpportunityStatus.WATCH.value: frozenset(
        {
            OpportunityStatus.ACTIVE.value,
            OpportunityStatus.OUTREACH_READY.value,
            OpportunityStatus.NURTURE.value,
            OpportunityStatus.CLOSED.value,
        }
    ),
    OpportunityStatus.NURTURE.value: frozenset(
        {
            OpportunityStatus.ACTIVE.value,
            OpportunityStatus.OUTREACH_READY.value,
            OpportunityStatus.WATCH.value,
            OpportunityStatus.CLOSED.value,
        }
    ),
    OpportunityStatus.SUPERSEDED.value: frozenset(),
    OpportunityStatus.REJECTED.value: frozenset({OpportunityStatus.CLOSED.value}),
    OpportunityStatus.CLOSED.value: frozenset(),
}


class LifecycleError(ValueError):
    """Illegal lifecycle transition."""


def can_transition_company(current: str, new: str) -> bool:
    if current == new:
        return True
    return new in _COMPANY_TRANSITIONS.get(current, frozenset())


def can_transition_opportunity(current: str, new: str) -> bool:
    if current == new:
        return True
    return new in _OPPORTUNITY_TRANSITIONS.get(current, frozenset())


def transition_company(company: Company, new_status: str) -> None:
    if not can_transition_company(company.status, new_status):
        raise LifecycleError(
            f"Cannot move company from {company.status!r} to {new_status!r}"
        )
    company.status = new_status


def transition_opportunity(opportunity: Opportunity, new_status: str) -> None:
    if not can_transition_opportunity(opportunity.status, new_status):
        raise LifecycleError(
            f"Cannot move opportunity from {opportunity.status!r} to {new_status!r}"
        )
    opportunity.status = new_status


def ensure_company_qualified_for_outreach(company: Company) -> None:
    """When an opportunity becomes outreach-ready, bump researched → qualified."""
    if company.status == CompanyStatus.RESEARCHED.value:
        transition_company(company, CompanyStatus.QUALIFIED.value)
