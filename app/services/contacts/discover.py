"""Contact discovery pipeline: candidate pages → fetch → extract → merge."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, Person, SourceSnapshot, SourceType
from app.models.person import PersonDiscoveryStatus, PersonSource
from app.services.buyers.guardrails import (
    BuyerGuardrailError,
    assert_fetch_allowed,
    is_permitted_people_page,
)
from app.services.contacts.extract import (
    extract_generic_channels,
    extract_people_from_text,
)
from app.services.contacts.merge import (
    apply_manual_fields,
    archive_person,
    find_matching_person,
    upsert_company_channel,
    upsert_person_from_extraction,
)
from app.services.contacts.normalize import is_generic_inbox
from app.services.contacts.pages import candidate_people_urls
from app.services.contacts.ssrf import UnsafeUrlError, assert_public_http_url
from app.services.fetcher import Fetcher, FetchResult

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, str], None]


def _emit(on_progress: ProgressFn | None, level: str, message: str) -> None:
    if on_progress is not None:
        on_progress(level, message)


@dataclass
class DiscoverContactsResult:
    company_id: UUID
    urls_tried: int = 0
    urls_fetched: int = 0
    urls_skipped_unchanged: int = 0
    urls_failed: int = 0
    people_created: int = 0
    people_enriched: int = 0
    channels_added: int = 0
    errors: list[str] = field(default_factory=list)
    message: str = ""
    # Human-readable findings for live UI logs (name, role, email?, action).
    findings: list[dict[str, str]] = field(default_factory=list)


def discover_contacts_for_company(
    session: Session,
    company_id: UUID,
    *,
    fetcher: Fetcher | None = None,
    max_urls: int = 12,
    refresh: bool = False,
    on_progress: ProgressFn | None = None,
) -> DiscoverContactsResult:
    """Fetch permitted people pages and upsert contacts. Partial success is OK."""
    company = session.scalar(
        select(Company)
        .where(Company.id == company_id)
        .options(selectinload(Company.snapshots))
    )
    if company is None:
        raise LookupError(f"Company {company_id} not found")

    result = DiscoverContactsResult(company_id=company.id)
    owns_fetcher = fetcher is None
    fetcher = fetcher or Fetcher()
    try:
        urls = candidate_people_urls(company, list(company.snapshots))[:max_urls]
        _emit(
            on_progress,
            "info",
            f"Planning {len(urls)} page(s) on {company.domain}",
        )
        # Always re-scan existing permitted snapshots (idempotent merge).
        _emit(on_progress, "info", "Reading pages already saved for this company…")
        _ingest_existing_snapshots(session, company, result, on_progress=on_progress)

        total = len(urls)
        for idx, url in enumerate(urls, start=1):
            result.urls_tried += 1
            _emit(on_progress, "info", f"Looking [{idx}/{total}] {url}")
            try:
                assert_fetch_allowed(url)
                assert_public_http_url(url)
            except (BuyerGuardrailError, UnsafeUrlError) as exc:
                result.urls_failed += 1
                result.errors.append(str(exc))
                _emit(on_progress, "warn", f"Skipped {url} — {exc}")
                continue

            latest = _latest_snapshot(session, company.id, url)
            etag = None
            last_modified = None
            previous_hash = None
            if latest:
                previous_hash = latest.content_hash
                meta = latest.metadata_json or {}
                etag = meta.get("etag")
                last_modified = meta.get("last_modified")
                if not refresh and latest.text:
                    # Already ingested via _ingest_existing_snapshots; skip re-fetch
                    # unless content may have changed (always try conditional GET).
                    pass

            try:
                _emit(on_progress, "info", f"Fetching {url}")
                fetch = fetcher.fetch(
                    url, etag=etag, last_modified=last_modified, previous_hash=previous_hash
                )
            except Exception as exc:  # noqa: BLE001
                result.urls_failed += 1
                result.errors.append(f"{url}: {exc}")
                logger.warning("contact discover fetch failed %s: %s", url, exc)
                _emit(on_progress, "warn", f"Failed {url} — {exc}")
                continue

            if fetch.blocked_by_robots:
                result.urls_failed += 1
                result.errors.append(f"{url}: blocked by robots.txt")
                _emit(on_progress, "warn", f"Blocked by robots.txt — {url}")
                continue
            if not fetch.ok:
                result.urls_failed += 1
                result.errors.append(f"{url}: {fetch.error or 'fetch failed'}")
                _emit(
                    on_progress,
                    "warn",
                    f"HTTP {fetch.http_status or '?'} — {url}",
                )
                continue
            if fetch.not_modified or not fetch.changed:
                result.urls_skipped_unchanged += 1
                _emit(on_progress, "info", f"Unchanged — re-reading saved text · {url}")
                if latest:
                    before = result.people_created + result.people_enriched
                    _apply_text(
                        session,
                        company,
                        latest.url,
                        latest.text,
                        snapshot=latest,
                        result=result,
                    )
                    found = (result.people_created + result.people_enriched) - before
                    if found:
                        _emit(on_progress, "ok", f"Found {found} contact hit(s) on {url}")
                continue

            result.urls_fetched += 1
            _emit(on_progress, "info", f"Extracting contacts from {url}")
            snapshot = _persist_snapshot(session, company, fetch, previous_hash=previous_hash)
            if snapshot and fetch.extracted:
                before = result.people_created + result.people_enriched
                _apply_text(
                    session,
                    company,
                    snapshot.url,
                    fetch.extracted.text,
                    snapshot=snapshot,
                    result=result,
                )
                found = (result.people_created + result.people_enriched) - before
                if found:
                    _emit(on_progress, "ok", f"Found {found} contact hit(s) on {url}")
                else:
                    _emit(on_progress, "info", f"No named contacts on {url}")
    finally:
        if owns_fetcher:
            fetcher.close()

    result.message = (
        f"Contacts: +{result.people_created} new, {result.people_enriched} enriched, "
        f"{result.channels_added} company channels; "
        f"fetched {result.urls_fetched}/{result.urls_tried} pages"
    )
    _emit_findings_summary(on_progress, result)
    _emit(on_progress, "ok", result.message)
    session.flush()
    return result


def _emit_findings_summary(
    on_progress: ProgressFn | None, result: DiscoverContactsResult
) -> None:
    if not result.findings:
        _emit(on_progress, "info", "Findings: no named contacts on public pages")
        return
    _emit(on_progress, "ok", f"Findings: {len(result.findings)} contact(s)")
    for item in result.findings[:20]:
        bits = [item.get("name") or "?", item.get("role") or ""]
        line = " — ".join(b for b in bits if b)
        if item.get("email"):
            line += f" · {item['email']}"
        action = item.get("action") or ""
        if action:
            line += f" ({action})"
        _emit(on_progress, "ok", f"· {line}")
    if len(result.findings) > 20:
        _emit(
            on_progress,
            "info",
            f"· …and {len(result.findings) - 20} more",
        )


def enrich_person(
    session: Session,
    person_id: UUID,
    *,
    fetcher: Fetcher | None = None,
) -> DiscoverContactsResult:
    """Re-run discovery for the person's company (bounded), then return stats."""
    person = session.get(Person, person_id)
    if person is None:
        raise LookupError("Person not found")
    return discover_contacts_for_company(
        session, person.company_id, fetcher=fetcher, max_urls=8, refresh=True
    )


def add_manual_contact(
    session: Session,
    company: Company,
    *,
    name: str,
    role: str,
    public_email: str | None = None,
    public_profile_url: str | None = None,
    public_phone: str | None = None,
    department: str | None = None,
    seniority: str | None = None,
    notes: str | None = None,
    mark_verified: bool = False,
) -> Person:
    from app.services.contacts.normalize import normalize_email as _norm_email

    name = name.strip()
    role = role.strip()
    if not name or not role:
        raise ValueError("name and role are required")
    # Operator-supplied email is trusted as manual research — never invent one.
    email = _norm_email((public_email or "").strip() or None)
    if email and is_generic_inbox(email):
        raise ValueError(
            "That looks like a company inbox (info@, sales@, …). "
            "Store it as a company channel, not a person email."
        )
    existing = find_matching_person(
        session, company_id=company.id, name=name, email=email
    )
    if existing:
        apply_manual_fields(
            existing,
            name=name,
            role=role,
            department=department,
            seniority=seniority,
            public_email=email,
            public_phone=public_phone,
            public_profile_url=(public_profile_url or "").strip() or None,
            notes=notes,
            mark_email_verified=mark_verified and bool(email),
            mark_profile_verified=mark_verified and bool(public_profile_url),
        )
        existing.source = existing.source or PersonSource.MANUAL.value
        session.flush()
        return existing

    from app.services.contacts.extract import ExtractedPerson

    extracted = ExtractedPerson(
        name=name[:255],
        role=role[:255],
        public_email=email,
        public_profile_url=(public_profile_url or "").strip() or None,
        public_phone=public_phone,
        department=department,
        seniority=seniority,
        excerpt="manual entry",
    )
    person, _ = upsert_person_from_extraction(
        session,
        company=company,
        extracted=extracted,
        source_url="manual",
        source=PersonSource.MANUAL.value,
    )
    apply_manual_fields(
        person,
        notes=notes,
        mark_email_verified=mark_verified and bool(email),
        mark_profile_verified=mark_verified and bool(public_profile_url),
    )
    if mark_verified:
        person.discovery_status = PersonDiscoveryStatus.ENRICHED.value
    session.flush()
    return person


def delete_or_archive_contact(
    session: Session, person_id: UUID, *, hard_delete: bool = False
) -> None:
    person = session.get(Person, person_id)
    if person is None:
        raise LookupError("Person not found")
    if hard_delete:
        session.delete(person)
    else:
        archive_person(person)
    session.flush()


def _ingest_existing_snapshots(
    session: Session,
    company: Company,
    result: DiscoverContactsResult,
    *,
    on_progress: ProgressFn | None = None,
) -> None:
    for snap in company.snapshots:
        if not is_permitted_people_page(snap.url):
            continue
        _emit(on_progress, "info", f"Reading saved page · {snap.url}")
        _apply_text(
            session,
            company,
            snap.url,
            snap.text,
            snapshot=snap,
            result=result,
        )


def _apply_text(
    session: Session,
    company: Company,
    source_url: str,
    text: str,
    *,
    snapshot: SourceSnapshot | None,
    result: DiscoverContactsResult,
) -> None:
    for extracted in extract_people_from_text(text, company_domain=company.domain):
        person, created = upsert_person_from_extraction(
            session,
            company=company,
            extracted=extracted,
            source_url=source_url,
            snapshot=snapshot,
        )
        if created:
            result.people_created += 1
            action = "new"
        else:
            result.people_enriched += 1
            action = "updated"
        finding = {
            "name": person.name or extracted.name or "?",
            "role": person.role or extracted.role or "",
            "action": action,
        }
        if person.public_email:
            finding["email"] = person.public_email
        # Dedupe by name+role so re-scans of saved pages don't flood the log.
        key = f"{finding['name'].casefold()}|{finding['role'].casefold()}"
        if not any(
            f"{f.get('name', '').casefold()}|{f.get('role', '').casefold()}" == key
            for f in result.findings
        ):
            result.findings.append(finding)
    for channel in extract_generic_channels(text):
        _row, created = upsert_company_channel(
            session,
            company=company,
            channel=channel,
            source_url=source_url,
            snapshot=snapshot,
        )
        if created:
            result.channels_added += 1


def _latest_snapshot(
    session: Session, company_id: UUID, url: str
) -> SourceSnapshot | None:
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
    previous_hash: str | None,
) -> SourceSnapshot | None:
    if fetch.extracted is None:
        return None
    meta = {
        **fetch.metadata,
        "etag": fetch.etag,
        "last_modified": fetch.last_modified,
        "final_url": fetch.final_url,
        "purpose": "contact_discovery",
    }
    snapshot = SourceSnapshot(
        company_id=company.id,
        url=fetch.url,
        source_type=SourceType.COMPANY_PAGE.value,
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
    session.flush()
    return snapshot
