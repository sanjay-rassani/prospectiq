"""Apply ICP and opportunity scores to persisted entities."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Company,
    CompanyStatus,
    Opportunity,
    OpportunityEvidence,
    OpportunityStatus,
    Signal,
)
from app.services.outreach.lifecycle import ensure_company_qualified_for_outreach
from app.services.scoring.exclusions import exclusion_reason
from app.services.scoring.icp import score_icp
from app.services.scoring.opportunity_score import score_opportunity
from app.services.scoring.profile import OperatorProfile, get_operator_profile
from app.services.scoring.promotion import apply_promotion_status

logger = logging.getLogger(__name__)


def apply_company_scores(
    session: Session,
    company: Company,
    profile: OperatorProfile | None = None,
) -> None:
    profile = profile or get_operator_profile()
    result = score_icp(company, profile)
    company.icp_score = round(result.total, 2)
    company.icp_reasons_json = result.reasons_dict()

    excl = exclusion_reason(company, profile)
    if excl:
        company.exclusion_reason = excl
        if company.status not in {
            CompanyStatus.CLOSED.value,
            CompanyStatus.DISQUALIFIED.value,
        }:
            company.status = CompanyStatus.DISQUALIFIED.value
        company.priority = "reject"
    else:
        company.exclusion_reason = None
        if result.total >= profile.thresholds.band_high:
            company.priority = "high"
        elif result.total >= profile.thresholds.band_medium:
            company.priority = "medium"
        elif result.total >= profile.thresholds.band_watch:
            company.priority = "watch"
        else:
            company.priority = "reject"
    session.flush()


def apply_opportunity_scores(
    session: Session,
    company: Company,
    opportunities: list[Opportunity] | None = None,
    profile: OperatorProfile | None = None,
    *,
    now: datetime | None = None,
) -> None:
    profile = profile or get_operator_profile()
    excl = exclusion_reason(company, profile)
    company_excluded = excl is not None

    if opportunities is None:
        opportunities = list(
            session.scalars(
                select(Opportunity)
                .where(
                    Opportunity.company_id == company.id,
                    Opportunity.status.in_(
                        [
                            OpportunityStatus.ACTIVE.value,
                            OpportunityStatus.OUTREACH_READY.value,
                        ]
                    ),
                )
                .options(
                    selectinload(Opportunity.evidence_links)
                    .selectinload(OpportunityEvidence.signal)
                    .selectinload(Signal.source_snapshot)
                )
            ).all()
        )

    for opp in opportunities:
        # Do not re-score / demote opportunities already in the outreach conversation path.
        if opp.status in {
            OpportunityStatus.CONTACTED.value,
            OpportunityStatus.REPLIED.value,
            OpportunityStatus.CONVERSATION.value,
            OpportunityStatus.PROJECT_LEAD.value,
            OpportunityStatus.NURTURE.value,
            OpportunityStatus.WATCH.value,
            OpportunityStatus.CLOSED.value,
            OpportunityStatus.REJECTED.value,
            OpportunityStatus.SUPERSEDED.value,
        }:
            continue
        result = score_opportunity(opp, profile, now=now)
        opp.opportunity_score = round(result.total, 2)
        opp.score_reasons_json = result.reasons_dict()
        opp.priority = result.band.value if result.band else None
        promoted = apply_promotion_status(
            opp,
            company_excluded=company_excluded,
            company_exclusion_reason=excl,
            profile=profile,
            now=now,
        )
        if promoted:
            ensure_company_qualified_for_outreach(company)
    session.flush()


def score_company_and_opportunities(
    session: Session,
    company: Company,
    profile: OperatorProfile | None = None,
) -> None:
    apply_company_scores(session, company, profile)
    opps = list(
        session.scalars(
            select(Opportunity)
            .where(Opportunity.company_id == company.id)
            .options(
                selectinload(Opportunity.evidence_links)
                .selectinload(OpportunityEvidence.signal)
                .selectinload(Signal.source_snapshot)
            )
        ).all()
    )
    active = [
        o
        for o in opps
        if o.status
        in {OpportunityStatus.ACTIVE.value, OpportunityStatus.OUTREACH_READY.value}
    ]
    apply_opportunity_scores(session, company, active, profile)
