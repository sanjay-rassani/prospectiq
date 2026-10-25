"""Persist and list Discover poll runs for the UI."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, JobStatus, JobType

_MAX_LOG_LINES = 80


def record_discovery_run(
    session: Session,
    *,
    stats: dict[str, Any] | None = None,
    summary: str,
    log_lines: list[str] | None = None,
    ok: bool = True,
    error: str | None = None,
    source: str = "stream",
) -> Job:
    """Write a completed/failed discover_leads job row used as run history."""
    now = datetime.now(UTC)
    stats = dict(stats or {})
    created = int(stats.get("created") or 0)
    # Empty runs (+0 new): keep only the latest — drop prior +0 new history rows.
    if ok and created == 0:
        _delete_zero_new_runs(session)
    outcome = _friendly_outcome(stats, summary=summary, ok=ok, error=error)
    payload: dict[str, Any] = {
        "outcome": outcome[:500],
        "summary": (summary or "")[:500],
        "source": source,
        "stats": {
            "created": created,
            "updated": int(stats.get("updated") or 0),
            "filtered": int(stats.get("filtered") or 0),
            "seeded": int(stats.get("seeded") or 0),
            "errors": int(stats.get("errors") or 0),
            "sources_run": int(stats.get("sources_run") or 0),
        },
        "log_lines": [(line or "")[:400] for line in (log_lines or [])[-_MAX_LOG_LINES:]],
    }
    job = Job(
        job_type=JobType.DISCOVER_LEADS.value,
        entity_id=None,
        due_at=now,
        status=JobStatus.DONE.value if ok else JobStatus.FAILED.value,
        attempts=1,
        completed_at=now,
        last_error=(error[:4000] if error and not ok else None),
        payload_json=payload,
        correlation_id=f"discover-{source}",
    )
    session.add(job)
    session.flush()
    return job


def attach_discovery_outcome(
    session: Session,
    job: Job,
    *,
    stats: dict[str, Any] | None = None,
    summary: str,
) -> None:
    """Store a short outcome on an existing scheduler job."""
    stats = dict(stats or {})
    created = int(stats.get("created") or 0)
    if created == 0:
        _delete_zero_new_runs(session, keep_job_id=job.id)
    payload = dict(job.payload_json or {})
    payload["outcome"] = _friendly_outcome(stats, summary=summary, ok=True)[:500]
    payload["summary"] = summary[:500]
    payload["stats"] = {
        "created": created,
        "updated": int(stats.get("updated") or 0),
        "filtered": int(stats.get("filtered") or 0),
        "seeded": int(stats.get("seeded") or 0),
        "errors": int(stats.get("errors") or 0),
        "sources_run": int(stats.get("sources_run") or 0),
    }
    job.payload_json = payload


def _is_zero_new_run(job: Job) -> bool:
    if job.status != JobStatus.DONE.value:
        return False
    payload = job.payload_json or {}
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    if "created" in stats:
        return int(stats.get("created") or 0) == 0
    outcome = str(payload.get("outcome") or "").casefold()
    return outcome.startswith("+0 new")


def _delete_zero_new_runs(
    session: Session,
    *,
    keep_job_id: object | None = None,
) -> int:
    """Remove prior successful discovery runs that found no new leads."""
    jobs = list(
        session.scalars(
            select(Job).where(
                Job.job_type == JobType.DISCOVER_LEADS.value,
                Job.status == JobStatus.DONE.value,
            )
        ).all()
    )
    removed = 0
    for job in jobs:
        if keep_job_id is not None and job.id == keep_job_id:
            continue
        if _is_zero_new_run(job):
            session.delete(job)
            removed += 1
    if removed:
        session.flush()
    return removed


def list_discovery_runs(
    session: Session,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Recent Discover polls: datetime + short outcome (+ optional log lines)."""
    jobs = list(
        session.scalars(
            select(Job)
            .where(
                Job.job_type == JobType.DISCOVER_LEADS.value,
                Job.status.in_([JobStatus.DONE.value, JobStatus.FAILED.value]),
            )
            .order_by(Job.completed_at.desc().nulls_last(), Job.created_at.desc())
            .limit(limit)
        ).all()
    )
    rows: list[dict[str, Any]] = []
    for job in jobs:
        payload = job.payload_json or {}
        at = job.completed_at or job.created_at
        stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
        stored = str(payload.get("outcome") or payload.get("summary") or "").strip()
        if job.status == JobStatus.DONE.value:
            outcome = stored or _friendly_outcome(stats, summary="", ok=True)
            ok = True
        else:
            outcome = str(job.last_error or stored or "Discovery failed").strip()[:200]
            ok = False
        log_lines = payload.get("log_lines")
        if not isinstance(log_lines, list):
            log_lines = []
        rows.append(
            {
                "id": str(job.id),
                "at": at,
                "outcome": outcome,
                "ok": ok,
                "log_lines": [str(x) for x in log_lines[-_MAX_LOG_LINES:]],
            }
        )
    return rows


def _friendly_outcome(
    stats: dict[str, Any],
    *,
    summary: str,
    ok: bool,
    error: str | None = None,
) -> str:
    if not ok:
        return (error or summary or "Discovery failed").strip()[:200]
    created = int(stats.get("created") or 0)
    updated = int(stats.get("updated") or 0)
    seeded = int(stats.get("seeded") or 0)
    filtered = int(stats.get("filtered") or 0)
    errors = int(stats.get("errors") or 0)
    bits = [f"+{created} new"]
    if updated:
        bits.append(f"{updated} updated")
    if seeded:
        bits.append(f"{seeded} seeded")
    if filtered:
        bits.append(f"{filtered} filtered")
    if errors:
        bits.append(f"{errors} source error(s)")
    line = " · ".join(bits)
    return line or (summary.strip()[:200] if summary else "No new leads")
