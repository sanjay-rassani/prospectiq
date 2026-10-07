"""Post-snapshot research pipeline: facts → signals → opportunities."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, Opportunity, Signal, SourceSnapshot
from app.services.buyers.service import process_buyers_for_company
from app.services.llm.facts import extract_company_facts
from app.services.llm.gateway import LlmGateway
from app.services.llm.opportunities import (
    generate_and_persist_opportunities,
    load_company_signals_for_generation,
)
from app.services.llm.signals import extract_and_persist_signals
from app.services.monitoring.cadence import apply_next_refresh
from app.services.monitoring.resurface import maybe_resurface
from app.services.scoring import score_company_and_opportunities

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    facts_ok: bool = False
    signals: list[Signal] = field(default_factory=list)
    signals_dropped: int = 0
    opportunities: list[Opportunity] = field(default_factory=list)
    scored: bool = False
    buyers: bool = False
    resurfaced: bool = False

    @property
    def summary(self) -> str:
        parts: list[str] = []
        if self.facts_ok:
            parts.append("facts")
        if self.signals:
            parts.append(f"{len(self.signals)} signals")
        if self.signals_dropped:
            parts.append(f"{self.signals_dropped} fabricated dropped")
        if self.opportunities:
            parts.append(f"{len(self.opportunities)} opportunities")
        if self.scored:
            parts.append("scored")
        if self.buyers:
            parts.append("buyers")
        if self.resurfaced:
            parts.append("resurfaced")
        return "; ".join(parts) if parts else "no LLM output"


def process_new_snapshot(
    session: Session,
    company: Company,
    snapshot: SourceSnapshot,
    gateway: LlmGateway | None = None,
) -> PipelineResult | None:
    """Run the Phase 3-8 research chain for a newly stored snapshot only.

    Unchanged re-fetches must never call this (AC-3 / P3-6).
    """
    if gateway is None and not get_settings().llm_enabled:
        return None

    result = PipelineResult()

    facts = extract_company_facts(session, company, snapshot, gateway=gateway)
    result.facts_ok = bool(facts and facts.ok)

    signals, _sig_call, dropped = extract_and_persist_signals(
        session, company, snapshot, gateway=gateway
    )
    result.signals = signals
    result.signals_dropped = dropped

    # P4-9: any newly persisted signal triggers opportunity re-evaluation.
    if signals:
        all_signals = load_company_signals_for_generation(session, company.id)
        opps, _opp_call = generate_and_persist_opportunities(
            session, company, snapshot, all_signals, gateway=gateway
        )
        result.opportunities = opps

    # Phase 5: always recompute ICP after facts; score opportunities when present.
    score_company_and_opportunities(session, company)
    result.scored = True

    # Phase 6: role recommendation, permitted-page person capture, research tasks.
    process_buyers_for_company(session, company, gateway=gateway)
    result.buyers = True

    # Phase 8: resurface dormant companies on meaningful (signal-producing) change.
    result.resurfaced = maybe_resurface(company, snapshot, signals)
    apply_next_refresh(company)

    return result
