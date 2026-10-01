"""Phase 7: outreach briefs, drafts, interactions, lifecycle, stop rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    CompanyStatus,
    Interaction,
    InteractionDirection,
    InteractionOutcome,
    Opportunity,
    OpportunityEvidence,
    OpportunityStatus,
    OutreachTaskStatus,
    Signal,
    SignalStrength,
    SignalType,
    SolutionFamily,
    SourceSnapshot,
    SourceType,
)
from app.services.outreach.brief import assemble_brief
from app.services.outreach.interactions import record_interaction
from app.services.outreach.lifecycle import LifecycleError, transition_company
from app.services.outreach.stop_rules import (
    apply_stale_evidence_rule,
    apply_unresponsive_rule,
)
from app.services.outreach.tasks import (
    approve_outreach,
    create_outreach_task,
    mark_sent,
    reject_outreach,
    save_draft,
)
from app.services.scoring.profile import OperatorProfile, OutreachSettings, ScoreThresholds
from tests.test_llm_facts import FakeGateway


def _seed_opportunity(session: Session) -> tuple[Company, Opportunity, Signal]:
    company = Company(
        name="Acme Outreach",
        domain="acme-outreach.example",
        industry="Logistics",
        size_hint="medium",
        status=CompanyStatus.RESEARCHED.value,
    )
    session.add(company)
    session.flush()
    snap = SourceSnapshot(
        company_id=company.id,
        url="https://acme-outreach.example/news",
        source_type=SourceType.COMPANY_PAGE.value,
        fetched_at=datetime.now(UTC),
        content_hash="d" * 64,
        title="News",
        text="Opened a third depot; spreadsheets still reconcile manually.",
        metadata_json={},
    )
    session.add(snap)
    session.flush()
    signal = Signal(
        company_id=company.id,
        source_snapshot_id=snap.id,
        type=SignalType.OPERATIONS.value,
        summary="Manual evening reconciliation across depots",
        evidence_excerpt="spreadsheets still reconcile manually",
        strength=SignalStrength.STRONG.value,
        observed_at=datetime.now(UTC),
    )
    session.add(signal)
    session.flush()
    opp = Opportunity(
        company_id=company.id,
        title="Automate depot reconciliation",
        solution_family=SolutionFamily.AGENTIC_AI_AUTOMATION.value,
        problem_or_change="Manual reconciliation",
        hypothesis="Build an ops workflow agent",
        business_outcome="Fewer evening reconciliations",
        why_now="Third depot opened",
        buyer_role="Head of Operations",
        confidence="high",
        status=OpportunityStatus.OUTREACH_READY.value,
        unknowns=["budget owner unclear"],
        opportunity_score=80.0,
        triggering_snapshot_id=snap.id,
    )
    session.add(opp)
    session.flush()
    session.add(
        OpportunityEvidence(
            opportunity_id=opp.id,
            signal_id=signal.id,
            source_snapshot_id=snap.id,
            note="primary evidence",
        )
    )
    session.flush()
    return company, opp, signal


def test_assemble_brief_is_deterministic(session: Session) -> None:
    company, opp, _signal = _seed_opportunity(session)
    from sqlalchemy.orm import selectinload

    opp = session.scalars(
        select(Opportunity)
        .where(Opportunity.id == opp.id)
        .options(
            selectinload(Opportunity.evidence_links).selectinload(OpportunityEvidence.signal)
        )
    ).one()
    brief = assemble_brief(company, opp, channel="linkedin")
    assert brief["company"]["name"] == "Acme Outreach"
    assert brief["why_now"] == "Third depot opened"
    assert brief["evidence"]
    assert brief["desired_conversation_goal"]
    assert "proposal" in brief["desired_conversation_goal"].casefold()


def test_milestone_brief_draft_approve_reply_next_action(session: Session) -> None:
    company, opp, _ = _seed_opportunity(session)
    gateway = FakeGateway()
    task = create_outreach_task(
        session, opp, company, channel="linkedin", gateway=gateway
    )
    assert task.brief_json["company"]["domain"] == "acme-outreach.example"
    assert task.draft
    assert task.status == OutreachTaskStatus.DRAFT_READY.value

    save_draft(task, task.draft + "\n\nWould a brief call help?")
    approve_outreach(task)
    assert task.status == OutreachTaskStatus.APPROVED.value
    assert task.approved_at is not None

    interaction = mark_sent(session, task, company, opp)
    assert task.status == OutreachTaskStatus.SENT.value
    assert interaction.outcome == InteractionOutcome.SENT.value
    assert interaction.next_action_at is not None
    assert opp.status == OpportunityStatus.CONTACTED.value
    assert company.status == CompanyStatus.CONTACTED.value

    reply = record_interaction(
        session,
        company,
        opp,
        channel="linkedin",
        direction=InteractionDirection.INBOUND.value,
        outcome=InteractionOutcome.REPLIED_INTERESTED.value,
        summary="They're open to a call next week",
        raw_text="Sounds interesting — free next Tuesday?",
        gateway=gateway,
    )
    assert reply.next_action_at is not None
    assert opp.status in {
        OpportunityStatus.REPLIED.value,
        OpportunityStatus.CONVERSATION.value,
    }
    assert company.status in {
        CompanyStatus.REPLIED.value,
        CompanyStatus.CONVERSATION.value,
    }


def test_reject_requires_reason(session: Session) -> None:
    company, opp, _ = _seed_opportunity(session)
    task = create_outreach_task(session, opp, company, gateway=None)
    save_draft(task, "Hello — noticed the third depot and spreadsheet reconciliation.")
    try:
        reject_outreach(task, "   ")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    reject_outreach(task, "Too generic")
    assert task.status == OutreachTaskStatus.REJECTED.value


def test_lifecycle_rejects_illegal_jump(session: Session) -> None:
    company, _, _ = _seed_opportunity(session)
    try:
        transition_company(company, CompanyStatus.PROJECT_LEAD.value)
        raise AssertionError("expected LifecycleError")
    except LifecycleError:
        pass


def test_unresponsive_nurture_after_n_touches(session: Session) -> None:
    company, opp, _ = _seed_opportunity(session)
    company.status = CompanyStatus.CONTACTED.value
    opp.status = OpportunityStatus.CONTACTED.value
    session.flush()
    profile = OperatorProfile(
        outreach=OutreachSettings(unresponsive_after_touches=2),
        thresholds=ScoreThresholds(),
    )
    for _ in range(2):
        session.add(
            Interaction(
                opportunity_id=opp.id,
                channel="linkedin",
                direction=InteractionDirection.OUTBOUND.value,
                occurred_at=datetime.now(UTC),
                summary="touch",
                outcome=InteractionOutcome.SENT.value,
            )
        )
    session.flush()
    action = apply_unresponsive_rule(session, company, opp, profile=profile)
    assert action and action.startswith("nurture:unresponsive")
    assert opp.status == OpportunityStatus.NURTURE.value
    assert company.status == CompanyStatus.NURTURE.value


def test_stale_evidence_moves_to_watch(session: Session) -> None:
    company, opp, signal = _seed_opportunity(session)
    company.status = CompanyStatus.QUALIFIED.value
    opp.status = OpportunityStatus.OUTREACH_READY.value
    signal.created_at = datetime.now(UTC) - timedelta(days=60)
    session.flush()
    profile = OperatorProfile(
        outreach=OutreachSettings(evidence_stale_days=45),
        thresholds=ScoreThresholds(),
    )
    action = apply_stale_evidence_rule(
        session, company, opp, profile=profile, now=datetime.now(UTC)
    )
    assert action and action.startswith("watch:evidence_stale")
    assert opp.status == OpportunityStatus.WATCH.value
    assert company.status == CompanyStatus.WATCH.value


def test_declined_outcome_nurtures(session: Session) -> None:
    company, opp, _ = _seed_opportunity(session)
    company.status = CompanyStatus.CONTACTED.value
    opp.status = OpportunityStatus.CONTACTED.value
    record_interaction(
        session,
        company,
        opp,
        channel="email",
        direction=InteractionDirection.INBOUND.value,
        outcome=InteractionOutcome.DECLINED.value,
        summary="Please remove us",
    )
    assert opp.status == OpportunityStatus.NURTURE.value
    assert company.status == CompanyStatus.NURTURE.value


def test_outreach_queue_page(client: object, session: Session) -> None:
    company, opp, _ = _seed_opportunity(session)
    create_outreach_task(session, opp, company, gateway=FakeGateway())
    session.flush()
    response = client.get("/outreach")  # type: ignore[attr-defined]
    assert response.status_code == 200
    assert b"Outreach queue" in response.content
    assert b"Automate depot reconciliation" in response.content
