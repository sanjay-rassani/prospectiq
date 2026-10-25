"""Persist and list website contact-scan outcomes for the UI."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, JobStatus, JobType
from app.services.contacts.discover import DiscoverContactsResult

_EXC_PREFIX = re.compile(
    r"^(?:RuntimeError|ValueError|LookupError|Exception|Error)\s*:\s*",
    re.I,
)


def humanize_scan_error(raw: str | None) -> str:
    """Turn fetch/exception text into a short operator-friendly line."""
    text = (raw or "").strip()
    if not text:
        return "Scan did not find contacts"
    text = _EXC_PREFIX.sub("", text).strip()

    n404 = len(re.findall(r"HTTP\s*404", text, re.I))
    n403 = len(re.findall(r"HTTP\s*403", text, re.I))
    n_other = len(re.findall(r"HTTP\s*(?!404|403)\d{3}", text, re.I))
    robots = "robots.txt" in text.casefold()
    timeout = "timeout" in text.casefold() or "timed out" in text.casefold()

    if n404 and not n403 and not n_other and not robots:
        if n404 == 1:
            return "No about/team page found (that URL was missing)"
        return f"No about/team pages found ({n404} URLs were missing)"
    if n403 and not n404 and not n_other:
        return "Company site blocked the scan (access denied)"
    if robots and not n404:
        return "Blocked by the site's robots.txt rules"
    if timeout:
        return "Company site was too slow to respond"
    if n404 or n403 or n_other:
        bits: list[str] = []
        if n404:
            bits.append(f"{n404} missing")
        if n403:
            bits.append(f"{n403} blocked")
        if n_other:
            bits.append(f"{n_other} other HTTP errors")
        return "Could not read team pages (" + ", ".join(bits) + ")"
    # Keep short; never dump raw exception stacks in the UI.
    short = re.sub(r"\s+", " ", text)
    if len(short) > 100:
        short = short[:97] + "…"
    if "http" in short.casefold() or "://" in short:
        return "Could not read public about/team pages"
    return short or "Scan did not find contacts"


def friendly_success_outcome(result: DiscoverContactsResult) -> str:
    """Compact success/empty line for history."""
    if result.people_created or result.people_enriched:
        line = f"+{result.people_created} new, {result.people_enriched} updated"
        if result.findings:
            line += f" · {len(result.findings)} listed"
        return line
    if result.errors:
        return humanize_scan_error("; ".join(result.errors[:5]))
    if result.urls_fetched == 0 and result.urls_tried:
        return "Tried team pages — none returned usable content"
    return "No named contacts on public pages"


def record_contact_scan(
    session: Session,
    company_id: UUID,
    *,
    result: DiscoverContactsResult | None = None,
    outcome: str,
    ok: bool = True,
    error: str | None = None,
    source: str = "stream",
) -> Job:
    """Write a completed/failed discover_contacts job row used as scan history."""
    now = datetime.now(UTC)
    friendly = (
        humanize_scan_error(error or outcome)
        if not ok
        else (friendly_success_outcome(result) if result is not None else outcome[:200])
    )
    payload: dict[str, Any] = {
        "outcome": friendly[:500],
        "source": source,
    }
    if result is not None:
        payload.update(
            {
                "created": result.people_created,
                "enriched": result.people_enriched,
                "channels": result.channels_added,
                "findings_count": len(result.findings),
                "urls_fetched": result.urls_fetched,
                "urls_tried": result.urls_tried,
            }
        )
    # Empty website results (404s, etc.) are "done" with a clear note — not hard fails.
    empty_result = (
        result is not None
        and not result.people_created
        and not result.people_enriched
    )
    status_ok = ok or empty_result
    if empty_result and result is not None:
        friendly = friendly_success_outcome(result)
        payload["outcome"] = friendly[:500]

    job = Job(
        job_type=JobType.DISCOVER_CONTACTS.value,
        entity_id=company_id,
        due_at=now,
        status=JobStatus.DONE.value if status_ok else JobStatus.FAILED.value,
        attempts=1,
        completed_at=now,
        last_error=(error[:4000] if error and not status_ok else None),
        payload_json=payload,
        correlation_id=f"scan-{source}",
    )
    session.add(job)
    session.flush()
    return job


def attach_outcome_to_job(
    job: Job,
    outcome: str,
    *,
    result: DiscoverContactsResult | None = None,
) -> None:
    """Store a short outcome on an existing job (scheduler path)."""
    payload = dict(job.payload_json or {})
    if result is not None:
        payload["outcome"] = friendly_success_outcome(result)[:500]
        payload["created"] = result.people_created
        payload["enriched"] = result.people_enriched
        payload["findings_count"] = len(result.findings)
    else:
        payload["outcome"] = humanize_scan_error(outcome)[:500]
    job.payload_json = payload


def list_contact_scans(
    session: Session,
    company_id: UUID,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Recent website contact scans: datetime + short outcome for Layer A history."""
    jobs = list(
        session.scalars(
            select(Job)
            .where(
                Job.entity_id == company_id,
                Job.job_type == JobType.DISCOVER_CONTACTS.value,
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
        stored = str(payload.get("outcome") or "").strip()
        created = payload.get("created")
        enriched = payload.get("enriched")
        findings = payload.get("findings_count")

        if job.status == JobStatus.DONE.value:
            if created is not None and enriched is not None and (created or enriched):
                outcome = f"+{created} new, {enriched} updated"
                if findings:
                    outcome += f" · {findings} listed"
            elif stored and not _looks_technical(stored):
                outcome = stored
            elif stored:
                outcome = humanize_scan_error(stored)
            else:
                outcome = "No named contacts on public pages"
            ok = True
        else:
            outcome = humanize_scan_error(job.last_error or stored or "Failed")
            ok = False

        rows.append({"at": at, "outcome": outcome, "ok": ok})
    return rows


def _looks_technical(text: str) -> bool:
    t = text.casefold()
    return (
        "runtimeerror" in t
        or "http 404" in t
        or "http 403" in t
        or "://" in t
        or t.startswith("error")
    )
