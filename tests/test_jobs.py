"""Phase 8: jobs, cadence, resurfacing, Today, restart safety."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.queue import (
    claim_due_jobs,
    enqueue_job,
    fail_job,
    recover_stale_locks,
)
from app.jobs.runner import process_due_jobs
from app.models import (
    Company,
    CompanyStatus,
    Job,
    JobStatus,
    JobType,
    Opportunity,
    OpportunityStatus,
    Signal,
    SignalStrength,
    SignalType,
    SourceSnapshot,
    SourceType,
)
from app.services.monitoring.cadence import apply_next_refresh, refresh_interval_days
from app.services.monitoring.resurface import maybe_resurface
from app.services.monitoring.today import load_today


def test_cadence_by_priority() -> None:
    company = Company(
        name="Cadence Co",
        domain="cadence.example",
        priority="high",
        status=CompanyStatus.QUALIFIED.value,
    )
    assert refresh_interval_days(company) == 2
    company.priority = "medium"
    assert refresh_interval_days(company) == 7
    company.status = CompanyStatus.WATCH.value
    assert refresh_interval_days(company) == 14
    company.status = CompanyStatus.NURTURE.value
    assert refresh_interval_days(company) == 30


def test_apply_next_refresh_sets_future(session: Session) -> None:
    company = Company(
        name="Refresh Co",
        domain="refresh-co.example",
        priority="medium",
        status=CompanyStatus.RESEARCHED.value,
        last_researched_at=datetime.now(UTC),
    )
    session.add(company)
    session.flush()
    due = apply_next_refresh(company)
    assert due is not None
    assert due > datetime.now(UTC)
    assert company.next_refresh_at == due


def test_resurface_on_meaningful_change(session: Session) -> None:
    company = Company(
        name="Dormant Co",
        domain="dormant.example",
        status=CompanyStatus.WATCH.value,
        priority="watch",
    )
    session.add(company)
    session.flush()
    snap = SourceSnapshot(
        company_id=company.id,
        url="https://dormant.example/news",
        source_type=SourceType.COMPANY_PAGE.value,
        fetched_at=datetime.now(UTC),
        content_hash="e" * 64,
        previous_hash="f" * 64,
        title="Update",
        text="We launched a new platform.",
        metadata_json={},
    )
    session.add(snap)
    session.flush()
    signal = Signal(
        company_id=company.id,
        source_snapshot_id=snap.id,
        type=SignalType.PRODUCT.value,
        summary="New platform launched",
        evidence_excerpt="We launched a new platform.",
        strength=SignalStrength.STRONG.value,
    )
    assert maybe_resurface(company, snap, [signal]) is True
    assert company.status == CompanyStatus.RESEARCHED.value
    assert company.resurfaced_at is not None
    assert company.priority == "medium"


def test_trivial_change_without_signals_does_not_resurface(session: Session) -> None:
    company = Company(
        name="Quiet Co",
        domain="quiet.example",
        status=CompanyStatus.NURTURE.value,
        priority="nurture",
    )
    session.add(company)
    session.flush()
    snap = SourceSnapshot(
        company_id=company.id,
        url="https://quiet.example/",
        source_type=SourceType.COMPANY_PAGE.value,
        fetched_at=datetime.now(UTC),
        content_hash="a" * 64,
        previous_hash="b" * 64,
        title="Home",
        text="Welcome",
        metadata_json={},
    )
    assert maybe_resurface(company, snap, []) is False
    assert company.status == CompanyStatus.NURTURE.value


def test_enqueue_dedupes_pending(session: Session) -> None:
    company = Company(name="Job Co", domain="job-co.example", status="researched")
    session.add(company)
    session.flush()
    first = enqueue_job(
        session, JobType.REFRESH_COMPANY.value, entity_id=company.id, dedupe_pending=True
    )
    second = enqueue_job(
        session, JobType.REFRESH_COMPANY.value, entity_id=company.id, dedupe_pending=True
    )
    assert first is not None and second is not None
    assert first.id == second.id
    count = session.scalars(
        select(Job).where(Job.entity_id == company.id, Job.status == JobStatus.PENDING.value)
    ).all()
    assert len(count) == 1


def test_claim_and_backoff(session: Session) -> None:
    job = enqueue_job(
        session,
        JobType.FOLLOW_UP_REMINDER.value,
        entity_id=None,
        due_at=datetime.now(UTC) - timedelta(minutes=1),
        dedupe_pending=False,
    )
    assert job is not None
    claimed = claim_due_jobs(session, limit=5)
    assert any(j.id == job.id for j in claimed)
    session.refresh(job)
    assert job.status == JobStatus.RUNNING.value
    assert job.attempts == 1

    fail_job(job, "boom")
    assert job.status == JobStatus.PENDING.value

    # Exhaust retries → permanent failure.
    job.attempts = 5
    job.status = JobStatus.RUNNING.value
    fail_job(job, "final boom")
    assert job.status == JobStatus.FAILED.value


def test_restart_recovers_stale_lock(session: Session) -> None:
    job = Job(
        job_type=JobType.REFRESH_COMPANY.value,
        status=JobStatus.RUNNING.value,
        due_at=datetime.now(UTC) - timedelta(hours=2),
        locked_at=datetime.now(UTC) - timedelta(hours=2),
        attempts=1,
        payload_json={},
    )
    session.add(job)
    session.flush()
    recovered = recover_stale_locks(session, older_than_minutes=30)
    assert recovered == 1
    session.refresh(job)
    assert job.status == JobStatus.PENDING.value
    assert job.locked_at is None


def test_process_due_jobs_completes_follow_up(session: Session) -> None:
    from app.models import Interaction, InteractionDirection, InteractionOutcome, Opportunity

    company = Company(name="Proc Co", domain="proc.example", status="contacted")
    session.add(company)
    session.flush()
    opp = Opportunity(
        company_id=company.id,
        title="Opp",
        solution_family="integrations_apis",
        problem_or_change="p",
        hypothesis="h",
        business_outcome="b",
        why_now="now",
        buyer_role="CTO",
        confidence="medium",
        status=OpportunityStatus.CONTACTED.value,
        unknowns=[],
    )
    session.add(opp)
    session.flush()
    interaction = Interaction(
        opportunity_id=opp.id,
        channel="linkedin",
        direction=InteractionDirection.OUTBOUND.value,
        occurred_at=datetime.now(UTC),
        summary="sent",
        outcome=InteractionOutcome.SENT.value,
        next_action_at=datetime.now(UTC) - timedelta(minutes=1),
        next_action_note="ping",
    )
    session.add(interaction)
    session.flush()
    enqueue_job(
        session,
        JobType.FOLLOW_UP_REMINDER.value,
        entity_id=interaction.id,
        due_at=interaction.next_action_at,
        dedupe_pending=False,
    )
    session.commit()
    results = process_due_jobs(session, limit=5)
    assert results
    done = session.get(Job, results[0].id)
    assert done is not None
    assert done.status == JobStatus.DONE.value


def test_today_page(client: object, session: Session) -> None:
    company = Company(
        name="Today Co",
        domain="today.example",
        status="qualified",
        priority="high",
    )
    session.add(company)
    session.flush()
    session.add(
        Opportunity(
            company_id=company.id,
            title="High opp",
            solution_family="integrations_apis",
            problem_or_change="p",
            hypothesis="h",
            business_outcome="b",
            why_now="now",
            buyer_role="CTO",
            confidence="high",
            status=OpportunityStatus.OUTREACH_READY.value,
            priority="high",
            opportunity_score=90,
            unknowns=[],
        )
    )
    session.flush()
    payload = load_today(session)
    assert len(payload["high_priority"]) == 1  # type: ignore[arg-type]
    response = client.get("/")  # type: ignore[attr-defined]
    assert response.status_code == 200
    assert b"High opp" in response.content
