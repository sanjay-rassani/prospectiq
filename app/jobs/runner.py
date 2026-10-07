"""Process claimed jobs in a single tick."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.jobs.handlers import handle_job
from app.jobs.queue import claim_due_jobs, complete_job, fail_job, recover_stale_locks
from app.models import Job

logger = logging.getLogger(__name__)


def process_due_jobs(session: Session, *, limit: int = 10) -> list[Job]:
    """Claim and run due jobs one at a time with per-job commit boundaries."""
    recover_stale_locks(session)
    session.commit()

    claimed = claim_due_jobs(session, limit=limit)
    session.commit()
    results: list[Job] = []

    for claimed_job in claimed:
        job_id = claimed_job.id
        corr = claimed_job.correlation_id or str(job_id)
        job = session.get(Job, job_id)
        if job is None:
            continue
        try:
            logger.info(
                "job_start correlation_id=%s job_id=%s type=%s attempt=%s",
                corr,
                job.id,
                job.job_type,
                job.attempts,
                extra={"correlation_id": corr},
            )
            summary = handle_job(session, job)
            complete_job(job)
            session.commit()
            logger.info(
                "job_done correlation_id=%s job_id=%s summary=%s",
                corr,
                job.id,
                summary,
            )
        except Exception as exc:
            session.rollback()
            job = session.get(Job, job_id)
            if job is not None:
                fail_job(job, f"{type(exc).__name__}: {exc}")
                session.commit()
            logger.exception("job_error correlation_id=%s job_id=%s", corr, job_id)
        results.append(session.get(Job, job_id) or claimed_job)
    return results
