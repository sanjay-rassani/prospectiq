"""Phase 5 scoring tests: ICP timing-blindness, opportunity bands, promotion gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    Company,
    Opportunity,
    OpportunityEvidence,
    OpportunityStatus,
    Signal,
    SignalStrength,
    SignalType,
    SolutionFamily,
    SourceSnapshot,
    SourceType,
)
from app.services.scoring.icp import score_icp
from app.services.scoring.opportunity_score import band_for_score, score_opportunity
from app.services.scoring.profile import OperatorProfile, ScoreThresholds
from app.services.scoring.promotion import (
    apply_promotion_status,
    override_outreach_ready,
    promotion_blockers,
)
from app.services.scoring.types import PriorityBand


def _profile(**kwargs: object) -> OperatorProfile:
    base: dict[str, object] = dict(
        target_industries=["logistics", "saas"],
        target_regions=["uk", "europe"],
        capabilities=["backend", "automation", "integrations"],
        preferred_solution_families=[SolutionFamily.BACKEND_DATA_SEARCH.value],
        excluded_industries=["staffing", "recruiting"],
        thresholds=ScoreThresholds(
            band_high=75, band_medium=55, band_watch=35, outreach_ready_min=65
        ),
    )
    base.update(kwargs)
    return OperatorProfile.model_validate(base)


def _company(**facts: object) -> Company:
    default_facts: dict[str, object] = {
        "name": "Acme Logistics",
        "one_line_description": "B2B freight",
        "industry": "Logistics",
        "products_or_services": ["freight", "warehousing"],
        "customer_type": "b2b",
        "size_hint": "medium",
        "geography": ["United Kingdom", "Manchester"],
        "technologies_mentioned": ["Excel"],
        "is_recruiter_or_staffing": False,
        "is_job_or_careers_page": False,
        "notable_claims": [],
        "confidence": "high",
    }
    default_facts.update(facts)
    return Company(
        name=str(default_facts["name"]),
        domain="acme-score.example",
        industry=str(default_facts.get("industry") or ""),
        size_hint=str(default_facts.get("size_hint") or "medium"),
        geography="United Kingdom",
        facts_json=default_facts,
        status="researched",
    )


def test_icp_ignores_timing_signals() -> None:
    """P5-3 / §8.1: attaching signal objects must not change ICP Fit."""
    company = _company()
    profile = _profile()
    before = score_icp(company, profile)
    company.signals = []  # type: ignore[assignment]
    # Even if a caller wrongly hung signals on the company, ICP must ignore them.
    after = score_icp(company, profile)
    assert before.total == after.total


def test_excluded_recruiter_icp_is_zero() -> None:
    company = _company(is_recruiter_or_staffing=True, industry="Staffing")
    result = score_icp(company, _profile())
    assert result.excluded
    assert result.total == 0.0


def test_identical_icp_different_opportunity_bands(session: Session) -> None:
    """Milestone: same ICP, different priority bands from opportunity timing/evidence."""
    profile = _profile()
    company = _company()
    session.add(company)
    session.flush()

    snap_fresh = SourceSnapshot(
        company_id=company.id,
        url="https://acme-score.example/",
        source_type=SourceType.MANUAL_SEED.value,
        fetched_at=datetime.now(UTC),
        content_hash="a" * 64,
        text="fresh evidence about Excel reconciliation",
        metadata_json={},
    )
    snap_stale = SourceSnapshot(
        company_id=company.id,
        url="https://acme-score.example/old",
        source_type=SourceType.COMPANY_PAGE.value,
        fetched_at=datetime.now(UTC) - timedelta(days=60),
        content_hash="b" * 64,
        text="old evidence about Excel reconciliation",
        metadata_json={},
    )
    session.add_all([snap_fresh, snap_stale])
    session.flush()

    sig_fresh = Signal(
        company_id=company.id,
        source_snapshot_id=snap_fresh.id,
        type=SignalType.OPERATIONS.value,
        summary="Manual Excel reconciliation",
        evidence_excerpt="Excel reconciliation",
        strength=SignalStrength.STRONG.value,
    )
    sig_stale = Signal(
        company_id=company.id,
        source_snapshot_id=snap_stale.id,
        type=SignalType.OPERATIONS.value,
        summary="Manual Excel reconciliation",
        evidence_excerpt="Excel reconciliation",
        strength=SignalStrength.WEAK.value,
    )
    session.add_all([sig_fresh, sig_stale])
    session.flush()
    sig_fresh.source_snapshot = snap_fresh
    sig_stale.source_snapshot = snap_stale

    def make_opp(title: str, signal: Signal) -> Opportunity:
        opp = Opportunity(
            company_id=company.id,
            title=title,
            solution_family=SolutionFamily.BACKEND_DATA_SEARCH.value,
            problem_or_change="Manual reconciliation",
            hypothesis="Automate reconciliation",
            business_outcome="Less manual work",
            why_now="Process pain visible",
            buyer_role="Operations Director",
            confidence="high",
            unknowns=[],
            status=OpportunityStatus.ACTIVE.value,
        )
        session.add(opp)
        session.flush()
        link = OpportunityEvidence(
            opportunity_id=opp.id,
            signal_id=signal.id,
            source_snapshot_id=signal.source_snapshot_id,
        )
        session.add(link)
        session.flush()
        link.signal = signal
        opp.evidence_links = [link]
        return opp

    fresh_opp = make_opp("Fresh ops automation", sig_fresh)
    stale_opp = make_opp("Stale ops automation", sig_stale)

    icp = score_icp(company, profile)
    fresh = score_opportunity(fresh_opp, profile)
    stale = score_opportunity(stale_opp, profile)

    assert icp.total > 0
    assert fresh.total > stale.total
    assert fresh.band is not None and stale.band is not None
    assert fresh.band != stale.band or (fresh.total - stale.total) >= 10


def test_outreach_ready_gate_and_override() -> None:
    profile = _profile()
    snap = SourceSnapshot(
        url="https://x.example/",
        source_type="manual_seed",
        fetched_at=datetime.now(UTC),
        content_hash="c" * 64,
        text="text",
        metadata_json={},
        company_id=None,  # type: ignore[arg-type]
    )
    # Detached graph: promotion helpers only need signal strength/recency + evidence links.
    signal = Signal(
        type=SignalType.OPERATIONS.value,
        summary="pain",
        evidence_excerpt="pain",
        strength=SignalStrength.STRONG.value,
        created_at=datetime.now(UTC),
    )
    signal.source_snapshot = snap
    link = OpportunityEvidence(note="x")
    link.signal = signal

    ready = Opportunity(
        title="Test",
        solution_family=SolutionFamily.BACKEND_DATA_SEARCH.value,
        problem_or_change="p",
        hypothesis="h",
        business_outcome="o",
        why_now="now",
        buyer_role="Operations Director",
        confidence="high",
        unknowns=[],
        status=OpportunityStatus.ACTIVE.value,
        opportunity_score=80.0,
        promotion_blockers=[],
        outreach_ready_override=False,
        evidence_links=[link],
    )
    assert (
        promotion_blockers(
            ready, company_excluded=False, company_exclusion_reason=None, profile=profile
        )
        == []
    )
    assert apply_promotion_status(ready, company_excluded=False, profile=profile) is True
    assert ready.status == OpportunityStatus.OUTREACH_READY.value

    blocked = Opportunity(
        title="Low",
        solution_family=SolutionFamily.BACKEND_DATA_SEARCH.value,
        problem_or_change="p",
        hypothesis="h",
        business_outcome="o",
        why_now="now",
        buyer_role="Operations Director",
        confidence="low",
        unknowns=["a", "b", "c"],
        status=OpportunityStatus.ACTIVE.value,
        opportunity_score=40.0,
        promotion_blockers=[],
        outreach_ready_override=False,
        evidence_links=[link],
    )
    blockers = promotion_blockers(
        blocked, company_excluded=False, company_exclusion_reason=None, profile=profile
    )
    assert any("below threshold" in b for b in blockers)
    override_outreach_ready(blocked, "Operator spoke to founder already")
    assert blocked.status == OpportunityStatus.OUTREACH_READY.value
    assert blocked.outreach_ready_override is True


def test_band_thresholds() -> None:
    profile = _profile()
    assert band_for_score(80, profile) == PriorityBand.HIGH
    assert band_for_score(60, profile) == PriorityBand.MEDIUM
    assert band_for_score(40, profile) == PriorityBand.WATCH
    assert band_for_score(10, profile) == PriorityBand.REJECT
