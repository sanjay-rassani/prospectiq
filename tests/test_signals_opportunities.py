"""Phase 4: signals, evidence gate, opportunities, change-triggered re-eval."""

from __future__ import annotations

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Opportunity, OpportunityEvidence, OpportunityStatus, Signal
from app.services.discovery.seed import refresh_company, seed_targets
from app.services.fetcher import Fetcher
from app.services.llm.evidence import evidence_is_verbatim
from app.services.llm.schemas import (
    Confidence,
    ExtractedSignal,
    OpportunityHypothesis,
    OpportunityList,
    SignalList,
    SignalStrength,
    SignalType,
    SolutionFamily,
)
from tests.test_llm_facts import FakeGateway

PAGE = """<!DOCTYPE html><html><head><title>Acme</title></head>
<body><article>
<p>Acme Logistics has opened a third distribution centre in Manchester.
Our operations team currently coordinates all three sites using a shared set of
Excel spreadsheets, which our depot managers reconcile manually every evening.
We are also hiring for logistics and finance roles.</p>
</article></body></html>"""

PAGE_V2 = PAGE.replace(
    "Excel spreadsheets",
    "spreadsheet workbooks and email threads",
)


def _fetcher(html: str = PAGE) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=html, headers={"ETag": '"v1"'})

    s = Settings(per_domain_delay_seconds=0.0, max_concurrent_fetches=4)
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return Fetcher(settings=s, client=client, owns_client=True)


def _ops_signal() -> ExtractedSignal:
    return ExtractedSignal(
        type=SignalType.OPERATIONS,
        summary="Manual Excel reconciliation across three sites.",
        evidence_excerpt=(
            "shared set of Excel spreadsheets, which our depot managers reconcile manually"
        ),
        strength=SignalStrength.STRONG,
        observed_at=None,
    )


def _growth_signal() -> ExtractedSignal:
    return ExtractedSignal(
        type=SignalType.GROWTH_EXPANSION,
        summary="Opened a third distribution centre in Manchester.",
        evidence_excerpt="opened a third distribution centre in Manchester",
        strength=SignalStrength.STRONG,
        observed_at=None,
    )


def _hiring_signal() -> ExtractedSignal:
    return ExtractedSignal(
        type=SignalType.NEGATIVE_WEAK,
        summary="Hiring for logistics and finance.",
        evidence_excerpt="We are also hiring for logistics and finance roles.",
        strength=SignalStrength.WEAK,
        observed_at=None,
    )


def _fabricated_signal() -> ExtractedSignal:
    return ExtractedSignal(
        type=SignalType.AI,
        summary="Planning a large AI transformation.",
        evidence_excerpt="We are investing $2M in an AI transformation this quarter.",
        strength=SignalStrength.STRONG,
        observed_at=None,
    )


def _good_hypothesis() -> OpportunityHypothesis:
    return OpportunityHypothesis(
        title="Automate cross-site inventory reconciliation",
        problem_or_change="Manual evening reconciliation of shared Excel across three sites.",
        project_hypothesis="Build a data pipeline that reconciles depot inventory automatically.",
        solution_family=SolutionFamily.BACKEND_DATA_SEARCH,
        business_outcome="Reduce nightly manual work and reconciliation errors.",
        why_now="Third site opened and volume is growing while process is still manual.",
        buyer_role="Operations Director",
        confidence=Confidence.MEDIUM,
        risks_or_unknowns=["Unknown existing WMS footprint"],
        supporting_signal_indexes=[0, 1],
    )


def _negative_only_hypothesis() -> OpportunityHypothesis:
    return OpportunityHypothesis(
        title="Automate logistics-finance handoff because they are hiring",
        problem_or_change="Hiring suggests process friction.",
        project_hypothesis="Agentic workflow between logistics and finance.",
        solution_family=SolutionFamily.AGENTIC_AI_AUTOMATION,
        business_outcome="Lower coordination cost.",
        why_now="They are hiring.",
        buyer_role="COO",
        confidence=Confidence.LOW,
        risks_or_unknowns=["Hiring may be seasonal"],
        supporting_signal_indexes=[2],
    )


def test_evidence_verbatim_helper() -> None:
    source = "shared set of Excel spreadsheets, which our depot managers reconcile manually"
    assert evidence_is_verbatim(source, PAGE)
    assert not evidence_is_verbatim(
        "We are investing $2M in an AI transformation this quarter.", PAGE
    )


def test_fabricated_signals_are_dropped(session: Session) -> None:
    gateway = FakeGateway(
        signal_list=SignalList(
            signals=[_ops_signal(), _fabricated_signal()],
            no_signal_reason=None,
        ),
        opportunity_list=OpportunityList(
            opportunities=[
                OpportunityHypothesis(
                    title="Reconcile inventory automatically",
                    problem_or_change="Manual Excel reconciliation.",
                    project_hypothesis="Build a reconciliation service.",
                    solution_family=SolutionFamily.BACKEND_DATA_SEARCH,
                    business_outcome="Less manual work.",
                    why_now="Three sites, still on Excel.",
                    buyer_role="Operations Director",
                    confidence=Confidence.MEDIUM,
                    risks_or_unknowns=[],
                    supporting_signal_indexes=[0],
                )
            ],
            no_opportunity_reason=None,
        ),
    )
    outcomes = seed_targets(
        session,
        "https://acme-signals.example/",
        fetcher=_fetcher(),
        gateway=gateway,
    )
    assert outcomes[0].pipeline is not None
    assert outcomes[0].pipeline.signals_dropped == 1
    signals = session.scalars(select(Signal)).all()
    assert len(signals) == 1
    assert signals[0].type == SignalType.OPERATIONS.value
    assert "Excel" in signals[0].evidence_excerpt


def test_opportunities_created_with_evidence_links(session: Session) -> None:
    gateway = FakeGateway(
        signal_list=SignalList(
            signals=[_ops_signal(), _growth_signal(), _hiring_signal()],
            no_signal_reason=None,
        ),
        opportunity_list=OpportunityList(
            opportunities=[_good_hypothesis(), _negative_only_hypothesis()],
            no_opportunity_reason=None,
        ),
    )
    outcomes = seed_targets(
        session,
        "https://acme-opps.example/",
        fetcher=_fetcher(),
        gateway=gateway,
    )
    assert outcomes[0].pipeline is not None
    assert gateway.opportunity_calls == 1
    opps = session.scalars(
        select(Opportunity).where(Opportunity.status == OpportunityStatus.ACTIVE.value)
    ).all()
    assert len(opps) == 1
    assert opps[0].title.startswith("Automate cross-site")
    links = session.scalars(select(OpportunityEvidence)).all()
    assert len(links) == 2
    assert all(link.signal_id is not None for link in links)


def test_change_reevaluates_and_supersedes_prior_opportunities(session: Session) -> None:
    gateway = FakeGateway(
        signal_list=SignalList(signals=[_ops_signal(), _growth_signal()], no_signal_reason=None),
        opportunity_list=OpportunityList(
            opportunities=[_good_hypothesis()], no_opportunity_reason=None
        ),
    )
    seeded = seed_targets(
        session,
        "https://acme-reeval.example/",
        fetcher=_fetcher(PAGE),
        gateway=gateway,
    )
    company_id = seeded[0].company.id
    first_id = session.scalar(select(Opportunity.id))
    assert first_id is not None

    # Second pass: different ops excerpt matching PAGE_V2, new hypothesis title.
    gateway.signal_list = SignalList(
        signals=[
            ExtractedSignal(
                type=SignalType.OPERATIONS,
                summary="Manual spreadsheet/email reconciliation.",
                evidence_excerpt=(
                    "spreadsheet workbooks and email threads, which our depot managers "
                    "reconcile manually"
                ),
                strength=SignalStrength.STRONG,
                observed_at=None,
            ),
            _growth_signal(),
        ],
        no_signal_reason=None,
    )
    gateway.opportunity_list = OpportunityList(
        opportunities=[
            OpportunityHypothesis(
                title="Unify depot ops data after process change",
                problem_or_change="Reconciliation moved to workbooks and email.",
                project_hypothesis="Ops data platform across depots.",
                solution_family=SolutionFamily.BACKEND_DATA_SEARCH,
                business_outcome="Single source of truth for inventory.",
                why_now="Process changed while third site is active.",
                buyer_role="Operations Director",
                confidence=Confidence.MEDIUM,
                risks_or_unknowns=[],
                supporting_signal_indexes=[0, 1],
            )
        ],
        no_opportunity_reason=None,
    )

    refreshed = refresh_company(
        session, company_id, fetcher=_fetcher(PAGE_V2), gateway=gateway
    )
    assert refreshed.pipeline is not None
    assert refreshed.pipeline.opportunities

    statuses = dict(
        session.execute(select(Opportunity.title, Opportunity.status)).all()
    )
    assert statuses[_good_hypothesis().title] == OpportunityStatus.SUPERSEDED.value
    assert (
        statuses["Unify depot ops data after process change"]
        == OpportunityStatus.ACTIVE.value
    )
    assert session.scalar(select(func.count()).select_from(Opportunity)) == 2
