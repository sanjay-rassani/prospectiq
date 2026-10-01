"""Deterministic outreach brief assembly (spec §10.1). Never LLM-generated."""

from __future__ import annotations

from typing import Any

from app.models import Company, Opportunity, OpportunityEvidence, Person


def assemble_brief(
    company: Company,
    opportunity: Opportunity,
    *,
    person: Person | None = None,
    channel: str = "linkedin",
) -> dict[str, Any]:
    """Build the §10.1 brief from stored evidence only."""
    evidence: list[dict[str, str]] = []
    for link in opportunity.evidence_links or []:
        if not isinstance(link, OpportunityEvidence):
            continue
        if link.signal is None:
            continue
        evidence.append(
            {
                "type": link.signal.type,
                "summary": link.signal.summary,
                "excerpt": link.signal.evidence_excerpt,
                "strength": link.signal.strength,
            }
        )

    role = opportunity.buyer_role
    person_label = (
        f"{person.name} ({person.role})" if person is not None else f"role: {role}"
    )

    return {
        "company": {
            "name": company.name,
            "domain": company.domain,
            "industry": company.industry,
            "geography": company.geography,
        },
        "person_or_role": person_label,
        "buyer_role": role,
        "person_id": str(person.id) if person is not None else None,
        "observed_trigger": opportunity.why_now,
        "project_hypothesis": opportunity.hypothesis,
        "problem_or_change": opportunity.problem_or_change,
        "business_outcome": opportunity.business_outcome,
        "evidence": evidence,
        "why_now": opportunity.why_now,
        "desired_conversation_goal": (
            "A short conversation to test whether this hypothesis is worth exploring — "
            "not a proposal."
        ),
        "risks_or_unknowns": list(opportunity.unknowns or []),
        "suggested_channel": channel,
        "solution_family": opportunity.solution_family,
        "confidence": opportunity.confidence,
    }


def brief_as_markdown(brief: dict[str, Any]) -> str:
    """Human-readable brief for the UI and as LLM input context."""
    company = brief.get("company") or {}
    lines = [
        f"# Outreach brief — {company.get('name', 'Company')}",
        "",
        f"- Domain: {company.get('domain')}",
        f"- Person/role: {brief.get('person_or_role')}",
        f"- Channel: {brief.get('suggested_channel')}",
        f"- Solution family: {brief.get('solution_family')}",
        f"- Confidence: {brief.get('confidence')}",
        "",
        "## Observed trigger / why now",
        str(brief.get("why_now") or ""),
        "",
        "## Problem or change",
        str(brief.get("problem_or_change") or ""),
        "",
        "## Project hypothesis",
        str(brief.get("project_hypothesis") or ""),
        "",
        "## Business outcome",
        str(brief.get("business_outcome") or ""),
        "",
        "## Desired conversation goal",
        str(brief.get("desired_conversation_goal") or ""),
        "",
        "## Evidence",
    ]
    for item in brief.get("evidence") or []:
        lines.append(
            f"- [{item.get('type')}/{item.get('strength')}] {item.get('summary')}"
        )
        lines.append(f"  > {item.get('excerpt')}")
    unknowns = brief.get("risks_or_unknowns") or []
    lines.extend(["", "## Risks / unknowns"])
    if unknowns:
        lines.extend(f"- {u}" for u in unknowns)
    else:
        lines.append("- (none stated)")
    return "\n".join(lines)
