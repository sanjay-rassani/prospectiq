"""Enqueue and claim durable Job rows with row-level locking."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.models import Job, JobStatus
from app.services.scoring.profile import get_operator_profile

logger = logging.getLogger(__name__)


def enqueue_job(
    session: Session,
    job_type: str,
    *,
    entity_id: uuid.UUID | None = None,
    due_at: datetime | None = None,
    payload: dict[str, Any] | None = None,
    dedupe_pending: bool = True,
) -> Job | None:
    """Create a pending job. When dedupe_pending, skip if one already waits for entity."""
    due = due_at or datetime.now(UTC)
    if dedupe_pending and entity_id is not None:
        existing = session.scalar(
            select(Job).where(
                Job.job_type == job_type,
                Job.entity_id == entity_id,
                Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
            )
        )
        if existing is not None:
            if existing.due_at > due:
                existing.due_at = due
            return existing

    job = Job(
        job_type=job_type,
        entity_id=entity_id,
        due_at=due,
        status=JobStatus.PENDING.value,
        payload_json=payload or {},
        correlation_id=uuid.uuid4().hex[:16],
    )
    session.add(job)
    session.flush()
    return job


def claim_due_jobs(session: Session, *, limit: int = 10) -> list[Job]:
    """Claim due pending jobs using FOR UPDATE SKIP LOCKED (P8-3)."""
    now = datetime.now(UTC)
    ids_stmt = (
        select(Job.id)
        .where(
            Job.status == JobStatus.PENDING.value,
            Job.due_at <= now,
        )
        .order_by(Job.due_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    ids = list(session.scalars(ids_stmt).all())
    if not ids:
        return []

    session.execute(
        update(Job)
        .where(Job.id.in_(ids))
        .values(
            status=JobStatus.RUNNING.value,
            locked_at=now,
            attempts=Job.attempts + 1,
        )
    )
    session.flush()
    return list(
        session.scalars(select(Job).where(Job.id.in_(ids)).order_by(Job.due_at.asc())).all()
    )


def complete_job(job: Job) -> None:
    job.status = JobStatus.DONE.value
    job.completed_at = datetime.now(UTC)
    job.last_error = None


def fail_job(job: Job, error: str) -> None:
    """Fail with capped exponential backoff reschedule, or mark failed permanently."""
    profile = get_operator_profile()
    job.last_error = error[:4000]
    max_attempts = profile.outreach.max_job_attempts
    if job.attempts >= max_attempts:
        job.status = JobStatus.FAILED.value
        job.completed_at = datetime.now(UTC)
        logger.error(
            "job %s (%s) permanently failed after %s attempts: %s",
            job.id,
            job.job_type,
            job.attempts,
            error,
        )
        return

    base = profile.outreach.job_backoff_base_seconds
    delay = min(base * (2 ** max(job.attempts - 1, 0)), 3600 * 6)
    job.status = JobStatus.PENDING.value
    job.locked_at = None
    job.due_at = datetime.now(UTC) + timedelta(seconds=delay)
    logger.warning(
        "job %s (%s) attempt %s failed; retry in %ss: %s",
        job.id,
        job.job_type,
        job.attempts,
        delay,
        error,
    )


def recover_stale_locks(session: Session, *, older_than_minutes: int = 60) -> int:
    """Re-queue jobs stuck in running after a crash (restart safety)."""
    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    result = session.execute(
        update(Job)
        .where(
            Job.status == JobStatus.RUNNING.value,
            Job.locked_at.is_not(None),
            Job.locked_at < cutoff,
        )
        .values(status=JobStatus.PENDING.value, locked_at=None)
    )
    session.flush()
    return int(getattr(result, "rowcount", 0) or 0)


def ensure_pg_skip_locked_supported(session: Session) -> None:
    """Smoke the lock syntax once at startup; raises if Postgres is too old."""
    session.execute(text("SELECT 1 FOR UPDATE SKIP LOCKED"))
