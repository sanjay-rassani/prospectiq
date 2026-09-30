"""Manual seed and company-page refresh adapters (spec section 5.1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, CompanyStatus, SourceSnapshot, SourceType
from app.services.discovery.normalize import NormalizedTarget, parse_seed_blob
from app.services.fetcher import Fetcher, FetchResult
from app.services.llm.gateway import LlmGateway
from app.services.llm.pipeline import PipelineResult, process_new_snapshot

logger = logging.getLogger(__name__)


@dataclass
class SeedOutcome:
    company: Company
    created: bool
    snapshot: SourceSnapshot | None
    fetch: FetchResult
    message: str
    facts_extracted: bool = False
    pipeline: PipelineResult | None = None


@dataclass
class RefreshOutcome:
    company: Company
    snapshot: SourceSnapshot | None
    fetch: FetchResult
    message: str
    facts_extracted: bool = False
    pipeline: PipelineResult | None = None


def _latest_snapshot(session: Session, company_id: object, url: str) -> SourceSnapshot | None:
    return session.scalar(
        select(SourceSnapshot)
        .where(SourceSnapshot.company_id == company_id, SourceSnapshot.url == url)
        .order_by(SourceSnapshot.fetched_at.desc())
        .limit(1)
    )


def _persist_snapshot(
    session: Session,
    company: Company,
    fetch: FetchResult,
    *,
    source_type: SourceType,
    previous_hash: str | None,
) -> SourceSnapshot:
    assert fetch.extracted is not None
    meta = {
        **fetch.metadata,
        "etag": fetch.etag,
        "last_modified": fetch.last_modified,
        "final_url": fetch.final_url,
    }
    snapshot = SourceSnapshot(
        company_id=company.id,
        url=fetch.url,
        source_type=source_type.value,
        fetched_at=datetime.now(UTC),
        published_at=fetch.extracted.published_at,
        http_status=fetch.http_status,
        content_hash=fetch.extracted.content_hash,
        previous_hash=previous_hash,
        title=fetch.extracted.title,
        text=fetch.extracted.text,
        metadata_json=meta,
    )
    session.add(snapshot)
    company.last_researched_at = snapshot.fetched_at
    company.last_error = None
    placeholder = company.domain.split(".")[0]
    if fetch.extracted.title and company.name.lower() in {company.domain, placeholder}:
        company.name = fetch.extracted.title[:255]
    session.flush()
    return snapshot


def _run_pipeline(
    session: Session,
    company: Company,
    snapshot: SourceSnapshot | None,
    gateway: LlmGateway | None,
) -> PipelineResult | None:
    if snapshot is None:
        return None
    return process_new_snapshot(session, company, snapshot, gateway=gateway)


def get_or_create_company(
    session: Session, target: NormalizedTarget
) -> tuple[Company, bool]:
    existing = session.scalar(select(Company).where(Company.domain == target.domain))
    if existing:
        if target.url and not existing.seed_url:
            existing.seed_url = target.url
        return existing, False

    company = Company(
        name=target.name_hint or target.domain,
        domain=target.domain,
        seed_url=target.url,
        status=CompanyStatus.SEEDED.value,
    )
    session.add(company)
    session.flush()
    return company, True


def seed_targets(
    session: Session,
    blob: str,
    fetcher: Fetcher | None = None,
    gateway: LlmGateway | None = None,
) -> list[SeedOutcome]:
    """Seed companies; research pipeline runs only for newly stored snapshots."""
    targets = parse_seed_blob(blob)
    if not targets:
        return []

    owns = fetcher is None
    fetcher = fetcher or Fetcher()
    outcomes: list[SeedOutcome] = []
    try:
        for target in targets:
            company, created = get_or_create_company(session, target)
            latest = _latest_snapshot(session, company.id, target.url)
            fetch = fetcher.fetch(
                target.url,
                etag=(latest.metadata_json or {}).get("etag") if latest else None,
                last_modified=(latest.metadata_json or {}).get("last_modified")
                if latest
                else None,
                previous_hash=latest.content_hash if latest else None,
            )

            snapshot: SourceSnapshot | None = None
            pipeline: PipelineResult | None = None
            facts_extracted = False
            if fetch.ok and fetch.changed and fetch.extracted:
                snapshot = _persist_snapshot(
                    session,
                    company,
                    fetch,
                    source_type=SourceType.MANUAL_SEED if created else SourceType.COMPANY_PAGE,
                    previous_hash=latest.content_hash if latest else None,
                )
                pipeline = _run_pipeline(session, company, snapshot, gateway)
                facts_extracted = bool(pipeline and pipeline.facts_ok)
                message = "snapshot stored" if created else "content changed; snapshot stored"
                if pipeline and pipeline.summary != "no LLM output":
                    message += f"; {pipeline.summary}"
            elif fetch.ok and not fetch.changed:
                company.last_researched_at = datetime.now(UTC)
                company.last_error = None
                message = "unchanged; no new snapshot"
            else:
                company.last_error = fetch.error
                message = fetch.error or "fetch failed"

            outcomes.append(
                SeedOutcome(
                    company=company,
                    created=created,
                    snapshot=snapshot,
                    fetch=fetch,
                    message=message,
                    facts_extracted=facts_extracted,
                    pipeline=pipeline,
                )
            )
        session.flush()
        return outcomes
    finally:
        if owns:
            fetcher.close()


def refresh_company(
    session: Session,
    company_id: object,
    fetcher: Fetcher | None = None,
    gateway: LlmGateway | None = None,
) -> RefreshOutcome:
    """Re-fetch; research pipeline runs only when content changed."""
    company = session.scalar(
        select(Company)
        .where(Company.id == company_id)
        .options(selectinload(Company.snapshots))
    )
    if company is None:
        raise LookupError("company not found")

    url = company.seed_url
    latest: SourceSnapshot | None = None
    if company.snapshots:
        latest = company.snapshots[0]
        url = url or latest.url
    if not url:
        raise ValueError("company has no URL to refresh")

    owns = fetcher is None
    fetcher = fetcher or Fetcher()
    try:
        fetch = fetcher.fetch(
            url,
            etag=(latest.metadata_json or {}).get("etag") if latest else None,
            last_modified=(latest.metadata_json or {}).get("last_modified")
            if latest
            else None,
            previous_hash=latest.content_hash if latest else None,
        )
        snapshot: SourceSnapshot | None = None
        pipeline: PipelineResult | None = None
        facts_extracted = False
        if fetch.ok and fetch.changed and fetch.extracted:
            snapshot = _persist_snapshot(
                session,
                company,
                fetch,
                source_type=SourceType.COMPANY_PAGE,
                previous_hash=latest.content_hash if latest else None,
            )
            pipeline = _run_pipeline(session, company, snapshot, gateway)
            facts_extracted = bool(pipeline and pipeline.facts_ok)
            message = "content changed; snapshot stored"
            if pipeline and pipeline.summary != "no LLM output":
                message += f"; {pipeline.summary}"
        elif fetch.ok and not fetch.changed:
            company.last_researched_at = datetime.now(UTC)
            company.last_error = None
            message = "unchanged; no new snapshot"
        else:
            company.last_error = fetch.error
            message = fetch.error or "fetch failed"

        session.flush()
        return RefreshOutcome(
            company=company,
            snapshot=snapshot,
            fetch=fetch,
            message=message,
            facts_extracted=facts_extracted,
            pipeline=pipeline,
        )
    finally:
        if owns:
            fetcher.close()
