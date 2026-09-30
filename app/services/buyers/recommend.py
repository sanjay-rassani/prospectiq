"""recommend_buyer_role — vocabulary-constrained role + rationale (spec §9.1 / §15.1)."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.models import Company, Opportunity
from app.services.buyers.role_map import normalize_to_vocabulary, roles_for_family
from app.services.llm.gateway import CallResult, LlmGateway
from app.services.llm.schemas import BuyerRoleRecommendation

logger = logging.getLogger(__name__)


def recommend_buyer_role_deterministic(
    opportunity: Opportunity,
    company: Company,
) -> BuyerRoleRecommendation:
    """Pure Python recommendation. Always safe; used when LLM is off or rejects."""
    allowed = roles_for_family(
        opportunity.solution_family,
        industry=company.industry,
        description=company.description,
        name=company.name,
    )
    existing = (opportunity.buyer_role or "").strip()
    matched = normalize_to_vocabulary(existing, allowed) if existing else None
    if matched:
        return BuyerRoleRecommendation(
            role=matched,
            rationale=(
                f"Aligned free-form suggestion '{existing}' to the §9.1 vocabulary for "
                f"{opportunity.solution_family}."
            ),
        )

    size = (company.size_hint or "").casefold()
    if size in {"solo", "small"}:
        for role in allowed:
            if "founder" in role.casefold() or role.casefold().startswith("ceo"):
                return BuyerRoleRecommendation(
                    role=role,
                    rationale=(
                        f"Small/solo company — prefer founder/CEO for "
                        f"{opportunity.solution_family} per §9.1."
                    ),
                )

    role = allowed[0]
    return BuyerRoleRecommendation(
        role=role,
        rationale=f"Default §9.1 role for solution family {opportunity.solution_family}.",
    )


def recommend_buyer_role(
    opportunity: Opportunity,
    company: Company,
    *,
    gateway: LlmGateway | None = None,
    session: Session | None = None,
) -> BuyerRoleRecommendation:
    """Recommend a role. LLM output is clamped to the §9.1 vocabulary; never trusted raw."""
    allowed = roles_for_family(
        opportunity.solution_family,
        industry=company.industry,
        description=company.description,
        name=company.name,
    )
    fallback = recommend_buyer_role_deterministic(opportunity, company)

    if gateway is None:
        return fallback

    payload = {
        "title": opportunity.title,
        "solution_family": opportunity.solution_family,
        "problem_or_change": opportunity.problem_or_change,
        "hypothesis": opportunity.hypothesis,
        "why_now": opportunity.why_now,
        "model_suggested_role": opportunity.buyer_role,
        "company_size_hint": company.size_hint,
        "company_industry": company.industry,
        "allowed_roles": list(allowed),
    }
    result: CallResult = gateway.recommend_buyer_role(
        opportunity_json=json.dumps(payload, indent=2)
    )
    if session is not None:
        from app.services.llm.facts import persist_llm_call

        persist_llm_call(
            session,
            result,
            company_id=company.id,
            snapshot_id=opportunity.triggering_snapshot_id,
        )
    if not result.ok or not isinstance(result.parsed, BuyerRoleRecommendation):
        logger.warning(
            "recommend_buyer_role LLM failed for opportunity=%s; using deterministic",
            opportunity.id,
        )
        return fallback

    picked = normalize_to_vocabulary(result.parsed.role, allowed)
    if picked is None:
        logger.warning(
            "recommend_buyer_role returned out-of-vocab role %r; using deterministic",
            result.parsed.role,
        )
        return fallback
    rationale = result.parsed.rationale.strip() or fallback.rationale
    return BuyerRoleRecommendation(role=picked, rationale=rationale)


def apply_buyer_role(
    opportunity: Opportunity,
    recommendation: BuyerRoleRecommendation,
) -> None:
    opportunity.buyer_role = recommendation.role[:255]
    opportunity.buyer_role_rationale = recommendation.rationale
