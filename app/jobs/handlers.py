"""Idempotent job handlers (P8-4)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.queue import enqueue_job
from app.models import (
    Company,
    CompanyStatus,
    Interaction,
    Job,
    JobStatus,
    JobType,
    Opportunity,
    OpportunityStatus,
)
from app.services.outreach.stop_rules import apply_stale_evidence_rule
from app.services.scoring.profile import get_operator_profile

logger = logging.getLogger(__name__)


def handle_job(session: Session, job: Job) -> str:
    """Dispatch one claimed job. Returns a short result summary. Raises on failure."""
    if job.job_type == JobType.REFRESH_COMPANY.value:
        return _handle_refresh(session, job)
    if job.job_type == JobType.FOLLOW_UP_REMINDER.value:
        return _handle_follow_up(session, job)
    if job.job_type == JobType.ENQUEUE_DUE_REFRESHES.value:
        return _handle_enqueue_due_refreshes(session, job)
    if job.job_type == JobType.CHECK_STALE_EVIDENCE.value:
        return _handle_check_stale(session, job)
    if job.job_type == JobType.POLL_FEEDS.value:
        return _handle_poll_feeds(session, job)
    if job.job_type == JobType.DISCOVER_CONTACTS.value:
        return _handle_discover_contacts(session, job)
    if job.job_type == JobType.DISCOVER_LEADS.value:
        return _handle_discover_leads(session, job)
    raise ValueError(f"Unknown job type: {job.job_type}")


def _handle_refresh(session: Session, job: Job) -> str:
    from app.services.discovery.seed import refresh_company
    from app.services.monitoring.cadence import apply_next_refresh

    if job.entity_id is None:
        raise ValueError("refresh_company requires entity_id")
    outcome = refresh_company(session, job.entity_id)
    apply_next_refresh(outcome.company)
    return outcome.message


def _handle_follow_up(session: Session, job: Job) -> str:
    """Confirm a due interaction still exists. Today reads next_action_at directly."""
    if job.entity_id is None:
        raise ValueError("follow_up_reminder requires entity_id (interaction id)")
    interaction = session.get(Interaction, job.entity_id)
    if interaction is None:
        return "interaction missing; nothing to remind"
    if interaction.next_action_at is None:
        return "next_action cleared; skip"
    return f"follow-up due for opportunity {interaction.opportunity_id}"


def _handle_enqueue_due_refreshes(session: Session, job: Job) -> str:
    now = datetime.now(UTC)
    companies = session.scalars(
        select(Company).where(
            Company.next_refresh_at.is_not(None),
            Company.next_refresh_at <= now,
            Company.status.notin_(
                [CompanyStatus.DISQUALIFIED.value, CompanyStatus.CLOSED.value]
            ),
        )
    ).all()
    created = 0
    for company in companies:
        before_id = session.scalar(
            select(Job.id).where(
                Job.job_type == JobType.REFRESH_COMPANY.value,
                Job.entity_id == company.id,
                Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
            )
        )
        enqueue_job(
            session,
            JobType.REFRESH_COMPANY.value,
            entity_id=company.id,
            due_at=now,
            dedupe_pending=True,
        )
        if before_id is None:
            created += 1

    due_interactions = session.scalars(
        select(Interaction).where(
            Interaction.next_action_at.is_not(None),
            Interaction.next_action_at <= now,
        )
    ).all()
    followups = 0
    for item in due_interactions:
        before_id = session.scalar(
            select(Job.id).where(
                Job.job_type == JobType.FOLLOW_UP_REMINDER.value,
                Job.entity_id == item.id,
                Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
            )
        )
        enqueue_job(
            session,
            JobType.FOLLOW_UP_REMINDER.value,
            entity_id=item.id,
            due_at=item.next_action_at,
            dedupe_pending=True,
        )
        if before_id is None:
            followups += 1

    tick = get_operator_profile().outreach.scheduler_tick_seconds
    enqueue_job(
        session,
        JobType.ENQUEUE_DUE_REFRESHES.value,
        due_at=now + timedelta(seconds=tick),
        dedupe_pending=True,
    )
    return f"enqueued {created} refreshes, {followups} follow-ups"


def _handle_check_stale(session: Session, job: Job) -> str:
    opps = session.scalars(
        select(Opportunity).where(
            Opportunity.status.in_(
                [
                    OpportunityStatus.ACTIVE.value,
                    OpportunityStatus.OUTREACH_READY.value,
                    OpportunityStatus.WATCH.value,
                ]
            )
        )
    ).all()
    moved = 0
    for opp in opps:
        company = session.get(Company, opp.company_id)
        if company is None:
            continue
        action = apply_stale_evidence_rule(session, company, opp)
        if action:
            moved += 1
    enqueue_job(
        session,
        JobType.CHECK_STALE_EVIDENCE.value,
        due_at=datetime.now(UTC) + timedelta(days=1),
        dedupe_pending=True,
    )
    return f"stale check moved {moved}"


def _handle_poll_feeds(session: Session, job: Job) -> str:
    from app.services.discovery.rss import poll_all_feeds

    stats = poll_all_feeds(session)
    enqueue_job(
        session,
        JobType.POLL_FEEDS.value,
        due_at=datetime.now(UTC) + timedelta(hours=6),
        dedupe_pending=True,
    )
    return (
        f"feeds={stats['feeds']} new={stats['new_entries']} "
        f"seeded={stats['seeded']} errors={stats['errors']}"
    )


def _handle_discover_contacts(session: Session, job: Job) -> str:
    from app.services.contacts.discover import discover_contacts_for_company
    from app.services.contacts.scan_history import (
        attach_outcome_to_job,
        friendly_success_outcome,
    )

    if job.entity_id is None:
        raise ValueError("discover_contacts requires entity_id (company id)")
    payload = job.payload_json or {}
    # Preserve max_urls=0 (snapshot-only). `or 12` would wrongly treat 0 as missing.
    raw_max = payload.get("max_urls", 12)
    max_urls = 12 if raw_max is None else int(raw_max)
    result = discover_contacts_for_company(
        session,
        job.entity_id,
        max_urls=max_urls,
        refresh=bool(payload.get("refresh")),
    )
    # Missing about/team pages is a normal empty result, not a hard job failure.
    outcome = friendly_success_outcome(result)
    attach_outcome_to_job(job, outcome, result=result)
    return outcome


def _handle_discover_leads(session: Session, job: Job) -> str:
    from app.services.leads.engine import run_lead_discovery
    from app.services.leads.filters import filters_from_prefs
    from app.services.leads.run_history import attach_discovery_outcome
    from app.services.scoring.profile import get_operator_profile

    profile = get_operator_profile()
    filters = filters_from_prefs(profile.discovery, profile)
    stats = run_lead_discovery(session, filters)
    summary = (
        f"leads +{stats.created} updated={stats.updated} "
        f"seeded={stats.seeded} errors={len(stats.errors)}"
    )
    attach_discovery_outcome(
        session, job, stats=stats.as_dict(), summary=summary
    )
    return summary


def ensure_maintenance_jobs(session: Session) -> None:
    """Seed recurring maintenance jobs if none are pending/running."""
    now = datetime.now(UTC)
    for job_type, due in (
        (JobType.ENQUEUE_DUE_REFRESHES.value, now),
        (JobType.CHECK_STALE_EVIDENCE.value, now + timedelta(hours=1)),
        (JobType.POLL_FEEDS.value, now + timedelta(minutes=30)),
    ):
        existing = session.scalar(
            select(Job).where(
                Job.job_type == job_type,
                Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
            )
        )
        if existing is None:
            enqueue_job(session, job_type, due_at=due, dedupe_pending=False)
