"""Rank contacts for an opportunity using recommended buyer roles."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Opportunity, Person
from app.models.person import PersonDiscoveryStatus
from app.services.buyers.research_tasks import person_matches_role
from app.services.buyers.role_map import roles_for_family


@dataclass(frozen=True)
class RankedContact:
    person: Person
    relevance_score: int
    matched_roles: list[str]
    reason: str


def rank_contacts_for_opportunity(
    session: Session,
    opportunity: Opportunity,
    *,
    company: Company | None = None,
    limit: int = 25,
) -> list[RankedContact]:
    """
    Score company contacts against recommended buyer roles.

    Distinguishes observed titles from recommended roles in `reason`.
    Never treats a recommended role as verified decision-maker status.
    """
    people = list(
        session.scalars(
            select(Person)
            .where(Person.company_id == opportunity.company_id)
            .where(Person.archived_at.is_(None))
            .where(Person.discovery_status != PersonDiscoveryStatus.ARCHIVED.value)
        ).all()
    )
    if not people:
        return []

    if company is None:
        company = session.get(Company, opportunity.company_id)
    recommended: list[str] = []
    if opportunity.buyer_role:
        recommended.append(opportunity.buyer_role)
    if company is not None:
        for role in roles_for_family(
            opportunity.solution_family,
            industry=company.industry,
            description=company.description,
            name=company.name,
        ):
            if role not in recommended:
                recommended.append(role)

    ranked: list[RankedContact] = []
    for person in people:
        matched: list[str] = []
        score = int(person.quality_score or 0) // 5
        for role in recommended:
            if person_matches_role(person, role):
                matched.append(role)
                score += 45 if role == opportunity.buyer_role else 30
        if person.seniority in ("c-level", "founder", "executive", "vp", "head"):
            score += 10
        if person.public_email:
            score += 8
        if person.public_profile_url:
            score += 5

        if matched:
            reason = (
                f"Observed title “{person.role}” aligns with recommended buyer "
                f"role(s): {', '.join(matched)}. "
                "Recommended roles are ICP guidance, not verified decision-maker status."
            )
        else:
            reason = (
                f"Company contact with observed title “{person.role}”. "
                "Not a primary match for recommended buyer roles."
            )
            score = max(0, score - 10)

        ranked.append(
            RankedContact(
                person=person,
                relevance_score=min(100, score),
                matched_roles=matched,
                reason=reason,
            )
        )

    ranked.sort(key=lambda r: (-r.relevance_score, -(r.person.quality_score or 0)))
    return ranked[:limit]
