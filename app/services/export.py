"""JSON/CSV export of companies, opportunities, interactions (P10-2)."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, Interaction, Opportunity


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"not serializable: {type(value)}")


def export_companies_json(session: Session) -> str:
    companies = session.scalars(
        select(Company)
        .options(
            selectinload(Company.opportunities).selectinload(Opportunity.evidence_links),
            selectinload(Company.opportunities).selectinload(Opportunity.interactions),
        )
        .order_by(Company.domain)
    ).all()
    payload = []
    for company in companies:
        payload.append(
            {
                "id": company.id,
                "name": company.name,
                "domain": company.domain,
                "industry": company.industry,
                "status": company.status,
                "priority": company.priority,
                "icp_score": company.icp_score,
                "geography": company.geography,
                "exclusion_reason": company.exclusion_reason,
                "opportunities": [
                    {
                        "id": opp.id,
                        "title": opp.title,
                        "status": opp.status,
                        "solution_family": opp.solution_family,
                        "opportunity_score": opp.opportunity_score,
                        "priority": opp.priority,
                        "buyer_role": opp.buyer_role,
                        "hypothesis": opp.hypothesis,
                        "why_now": opp.why_now,
                        "evidence_count": len(opp.evidence_links or []),
                        "interactions": [
                            {
                                "id": item.id,
                                "channel": item.channel,
                                "direction": item.direction,
                                "outcome": item.outcome,
                                "summary": item.summary,
                                "occurred_at": item.occurred_at,
                                "next_action_at": item.next_action_at,
                            }
                            for item in (opp.interactions or [])
                        ],
                    }
                    for opp in (company.opportunities or [])
                ],
            }
        )
    return json.dumps(payload, default=_json_default, indent=2)


def export_opportunities_csv(session: Session) -> str:
    opps = session.scalars(
        select(Opportunity)
        .options(selectinload(Opportunity.company))
        .order_by(Opportunity.created_at.desc())
    ).all()
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "opportunity_id",
            "company",
            "domain",
            "title",
            "status",
            "solution_family",
            "opportunity_score",
            "priority",
            "buyer_role",
            "confidence",
        ],
    )
    writer.writeheader()
    for opp in opps:
        writer.writerow(
            {
                "opportunity_id": str(opp.id),
                "company": opp.company.name if opp.company else "",
                "domain": opp.company.domain if opp.company else "",
                "title": opp.title,
                "status": opp.status,
                "solution_family": opp.solution_family,
                "opportunity_score": opp.opportunity_score,
                "priority": opp.priority,
                "buyer_role": opp.buyer_role,
                "confidence": opp.confidence,
            }
        )
    return buf.getvalue()


def export_interactions_csv(session: Session) -> str:
    rows = session.scalars(
        select(Interaction)
        .options(selectinload(Interaction.opportunity).selectinload(Opportunity.company))
        .order_by(Interaction.occurred_at.desc())
    ).all()
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "interaction_id",
            "company",
            "opportunity",
            "channel",
            "direction",
            "outcome",
            "summary",
            "occurred_at",
            "next_action_at",
        ],
    )
    writer.writeheader()
    for item in rows:
        company = item.opportunity.company if item.opportunity else None
        writer.writerow(
            {
                "interaction_id": str(item.id),
                "company": company.name if company else "",
                "opportunity": item.opportunity.title if item.opportunity else "",
                "channel": item.channel,
                "direction": item.direction,
                "outcome": item.outcome,
                "summary": item.summary,
                "occurred_at": item.occurred_at.isoformat() if item.occurred_at else "",
                "next_action_at": (
                    item.next_action_at.isoformat() if item.next_action_at else ""
                ),
            }
        )
    return buf.getvalue()
