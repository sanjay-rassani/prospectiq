"""Today screen data assembly (spec §16 / P8-9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Company,
    Interaction,
    Opportunity,
    OpportunityStatus,
    OutreachTask,
    OutreachTaskStatus,
    SourceSnapshot,
)


def load_today(session: Session) -> dict[str, object]:
    now = datetime.now(UTC)
    since = now - timedelta(hours=48)

    high_priority = list(
        session.scalars(
            select(Opportunity)
            .where(
                Opportunity.status.in_(
                    [
                        OpportunityStatus.OUTREACH_READY.value,
                        OpportunityStatus.ACTIVE.value,
                        OpportunityStatus.CONTACTED.value,
                    ]
                ),
                Opportunity.priority == "high",
            )
            .options(selectinload(Opportunity.company))
            .order_by(Opportunity.opportunity_score.desc().nullslast())
            .limit(20)
        ).all()
    )

    due_outreach = list(
        session.scalars(
            select(OutreachTask)
            .where(
                OutreachTask.status.in_(
                    [
                        OutreachTaskStatus.DRAFT_READY.value,
                        OutreachTaskStatus.APPROVED.value,
                        OutreachTaskStatus.PENDING_DRAFT.value,
                    ]
                )
            )
            .options(
                selectinload(OutreachTask.opportunity).selectinload(Opportunity.company)
            )
            .order_by(OutreachTask.due_at.asc().nullslast())
            .limit(20)
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
            .limit(20)
        ).all()
    )

    newly_changed = list(
        session.scalars(
            select(SourceSnapshot)
            .where(
                SourceSnapshot.fetched_at >= since,
                SourceSnapshot.previous_hash.is_not(None),
            )
            .options(selectinload(SourceSnapshot.company))
            .order_by(SourceSnapshot.fetched_at.desc())
            .limit(20)
        ).all()
    )

    resurfaced = list(
        session.scalars(
            select(Company)
            .where(
                Company.resurfaced_at.is_not(None),
                Company.resurfaced_at >= since,
            )
            .order_by(Company.resurfaced_at.desc())
            .limit(20)
        ).all()
    )

    return {
        "high_priority": high_priority,
        "due_outreach": due_outreach,
        "due_followups": due_followups,
        "newly_changed": newly_changed,
        "resurfaced": resurfaced,
    }
