"""Orchestrate buyer-role recommendation, person capture, and research tasks."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Company,
    Opportunity,
    OpportunityStatus,
    Person,
    ResearchTask,
    ResearchTaskStatus,
)
from app.services.buyers.capture import capture_people_from_snapshots
from app.services.buyers.recommend import apply_buyer_role, recommend_buyer_role
from app.services.buyers.research_tasks import ensure_research_task
from app.services.llm.gateway import LlmGateway

logger = logging.getLogger(__name__)


def process_buyers_for_company(
    session: Session,
    company: Company,
    *,
    gateway: LlmGateway | None = None,
) -> dict[str, int]:
    """Capture people, recommend roles, and open research tasks as needed."""
    captured = capture_people_from_snapshots(session, company)

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
            .options(selectinload(Opportunity.research_tasks))
        ).all()
    )

    all_people = list(
        session.scalars(select(Person).where(Person.company_id == company.id)).all()
    )

    roles_applied = 0
    tasks_opened = 0
    for opp in opportunities:
        recommendation = recommend_buyer_role(
            opp, company, gateway=gateway, session=session
        )
        apply_buyer_role(opp, recommendation)
        roles_applied += 1
        _task, created = ensure_research_task(session, company, opp, people=all_people)
        if created:
            tasks_opened += 1

    open_count = session.scalar(
        select(func.count())
        .select_from(ResearchTask)
        .where(
            ResearchTask.company_id == company.id,
            ResearchTask.status == ResearchTaskStatus.OPEN.value,
        )
    )
    session.flush()
    logger.info(
        "buyers for company=%s: captured=%s roles=%s tasks_opened=%s",
        company.id,
        len(captured),
        roles_applied,
        tasks_opened,
    )
    return {
        "people_captured": len(captured),
        "roles_recommended": roles_applied,
        "research_tasks_opened": tasks_opened,
        "research_tasks_open": int(open_count or 0),
    }
