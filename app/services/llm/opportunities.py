"""generate_opportunities with deterministic citation and negative-evidence gates."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Company,
    CompanyStatus,
    Opportunity,
    OpportunityEvidence,
    OpportunityStatus,
    Signal,
    SignalType,
    SourceSnapshot,
)
from app.services.llm.facts import persist_llm_call
from app.services.llm.gateway import CallResult, LlmGateway, OllamaGateway
from app.services.llm.schemas import OpportunityHypothesis, OpportunityList

logger = logging.getLogger(__name__)


def _cites_only_negative(hypothesis: OpportunityHypothesis, signals: list[Signal]) -> bool:
    indexes = hypothesis.supporting_signal_indexes or []
    if not indexes:
        return True
    cited_types = []
    for i in indexes:
        if i < 0 or i >= len(signals):
            return True
        cited_types.append(signals[i].type)
    return bool(cited_types) and all(t == SignalType.NEGATIVE_WEAK.value for t in cited_types)


def _valid_citation_indexes(
    hypothesis: OpportunityHypothesis, signals: list[Signal]
) -> list[int] | None:
    indexes = hypothesis.supporting_signal_indexes or []
    if not indexes:
        return None
    if any(i < 0 or i >= len(signals) for i in indexes):
        return None
    return indexes


def supersede_active_opportunities(session: Session, company: Company) -> int:
    rows = session.scalars(
        select(Opportunity).where(
            Opportunity.company_id == company.id,
            Opportunity.status == OpportunityStatus.ACTIVE.value,
        )
    ).all()
    for row in rows:
        row.status = OpportunityStatus.SUPERSEDED.value
    session.flush()
    return len(rows)


def persist_opportunities(
    session: Session,
    company: Company,
    snapshot: SourceSnapshot,
    signals: list[Signal],
    hypotheses: list[OpportunityHypothesis],
) -> list[Opportunity]:
    """Persist hypotheses that cite real signals and are not negative-only."""
    created: list[Opportunity] = []
    for hyp in hypotheses:
        indexes = _valid_citation_indexes(hyp, signals)
        if indexes is None:
            logger.warning(
                "dropping opportunity with bad citations: %s -> %s",
                hyp.title,
                hyp.supporting_signal_indexes,
            )
            continue
        if _cites_only_negative(hyp, signals):
            logger.warning(
                "dropping negative-only opportunity (job-hunting drift): %s", hyp.title
            )
            continue

        opp = Opportunity(
            company_id=company.id,
            title=hyp.title[:512],
            solution_family=hyp.solution_family.value,
            problem_or_change=hyp.problem_or_change,
            hypothesis=hyp.project_hypothesis,
            business_outcome=hyp.business_outcome,
            why_now=hyp.why_now,
            buyer_role=hyp.buyer_role[:255],
            confidence=hyp.confidence.value,
            status=OpportunityStatus.ACTIVE.value,
            unknowns=list(hyp.risks_or_unknowns),
            triggering_snapshot_id=snapshot.id,
        )
        session.add(opp)
        session.flush()
        for i in indexes:
            session.add(
                OpportunityEvidence(
                    opportunity_id=opp.id,
                    signal_id=signals[i].id,
                    source_snapshot_id=signals[i].source_snapshot_id,
                    note=f"cited signal index {i}",
                )
            )
        created.append(opp)
    session.flush()
    return created


def generate_and_persist_opportunities(
    session: Session,
    company: Company,
    snapshot: SourceSnapshot,
    signals: list[Signal],
    gateway: LlmGateway | None = None,
) -> tuple[list[Opportunity], CallResult | None]:
    """Change-triggered re-evaluation (P4-9): supersede actives, then generate anew."""
    if company.status == CompanyStatus.DISQUALIFIED.value:
        return [], None
    if not signals:
        return [], None

    owns = gateway is None
    gateway = gateway or OllamaGateway()
    try:
        facts_payload = company.facts_json or {
            "name": company.name,
            "domain": company.domain,
            "description": company.description,
        }
        signals_payload = {
            "signals": [
                {
                    "type": s.type,
                    "summary": s.summary,
                    "evidence_excerpt": s.evidence_excerpt,
                    "strength": s.strength,
                    "observed_at": s.observed_at.isoformat() if s.observed_at else None,
                }
                for s in signals
            ]
        }
        result = gateway.generate_opportunities(
            facts_json=json.dumps(facts_payload, indent=2),
            signals_json=json.dumps(signals_payload, indent=2),
        )
        persist_llm_call(session, result, company_id=company.id, snapshot_id=snapshot.id)
        if not result.ok or not isinstance(result.parsed, OpportunityList):
            logger.warning(
                "opportunity generation failed for company=%s: %s",
                company.id,
                result.errors if result else None,
            )
            return [], result

        supersede_active_opportunities(session, company)
        created = persist_opportunities(
            session, company, snapshot, signals, result.parsed.opportunities
        )
        return created, result
    finally:
        if owns and isinstance(gateway, OllamaGateway):
            gateway.close()


def load_company_signals_for_generation(
    session: Session, company_id: object
) -> list[Signal]:
    """Use all signals for the company, newest first, for hypothesis generation."""
    return list(
        session.scalars(
            select(Signal)
            .where(Signal.company_id == company_id)
            .order_by(Signal.created_at.desc())
            .options(selectinload(Signal.source_snapshot))
        ).all()
    )
