"""Dedupe and persist discovery candidates as DiscoveryLead rows."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company
from app.models.lead import DiscoveryLead, LeadStatus
from app.services.contacts.ssrf import UnsafeUrlError, assert_public_http_url
from app.services.discovery.normalize import normalize_domain
from app.services.leads.adapters.base import RawCandidate
from app.services.leads.filters import TargetingFilters
from app.services.leads.scoring import score_candidate

LISTING_HOSTS = frozenset(
    {
        "news.ycombinator.com",
        "hn.algolia.com",
        "github.com",
        "www.github.com",
        "api.github.com",
        "contractsfinder.service.gov.uk",
        "www.contractsfinder.service.gov.uk",
        "find-tender.service.gov.uk",
        "ted.europa.eu",
        "reddit.com",
        "www.reddit.com",
    }
)


def persist_candidate(
    session: Session,
    raw: RawCandidate,
    filters: TargetingFilters,
) -> tuple[DiscoveryLead | None, str]:
    """Insert or refresh a lead.

    Action is created, updated, skipped_*, or rejected_kept.
    """
    try:
        assert_public_http_url(raw.url)
    except UnsafeUrlError:
        return None, "skipped_unsafe_url"

    scored = score_candidate(
        title=raw.title,
        description=raw.description,
        url=raw.url,
        source_category=raw.source_category,
        filters=filters,
        published_at=raw.published_at,
        location=raw.location,
        budget_text=raw.budget_text,
    )
    if scored.relevance < filters.min_relevance:
        return None, "skipped_low_score"

    existing = session.scalar(
        select(DiscoveryLead).where(
            DiscoveryLead.source_kind == raw.source_kind,
            DiscoveryLead.listing_id == raw.listing_id,
        )
    )
    now = datetime.now(UTC)
    if existing is None:
        by_url = session.scalar(
            select(DiscoveryLead).where(DiscoveryLead.canonical_url == raw.url[:2048])
        )
        existing = by_url

    if existing is not None:
        if existing.status == LeadStatus.REJECTED.value:
            # Keep operator rejection; refresh evidence only.
            existing.description = raw.description[:8000] or existing.description
            existing.excerpt = raw.excerpt or existing.excerpt
            session.flush()
            return existing, "rejected_kept"
        existing.title = raw.title[:512]
        existing.description = raw.description[:8000]
        existing.excerpt = raw.excerpt
        existing.intent_class = scored.intent_class
        existing.lead_kind = scored.lead_kind
        existing.relevance_score = scored.relevance
        existing.score_reasons_json = scored.reasons
        existing.matched_filters_json = scored.matched
        existing.detected_requirements_json = scored.requirements
        existing.buying_intent_indicators_json = scored.intent_indicators
        existing.location_text = raw.location
        existing.budget_text = raw.budget_text
        existing.published_at = raw.published_at or existing.published_at
        session.flush()
        return existing, "updated"

    lead = DiscoveryLead(
        source_kind=raw.source_kind,
        source_name=raw.source_name,
        source_category=raw.source_category,
        listing_id=raw.listing_id[:512],
        canonical_url=raw.url[:2048],
        title=raw.title[:512],
        description=raw.description[:8000],
        excerpt=raw.excerpt,
        lead_kind=scored.lead_kind,
        intent_class=scored.intent_class,
        relevance_score=scored.relevance,
        score_reasons_json=scored.reasons,
        matched_filters_json=scored.matched,
        detected_requirements_json=scored.requirements,
        buying_intent_indicators_json=scored.intent_indicators,
        location_text=raw.location,
        budget_text=raw.budget_text,
        contract_type=raw.contract_type,
        status=LeadStatus.NEW.value,
        discovered_at=now,
        published_at=raw.published_at,
        raw_json=raw.extra or {},
    )
    session.add(lead)
    session.flush()
    return lead, "created"


def listing_host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def company_domain_from_lead(lead: DiscoveryLead) -> str | None:
    """Best-effort domain for pipeline save. Listing hosts are not companies."""
    host = listing_host(lead.canonical_url)
    if host and host not in LISTING_HOSTS and not any(
        host.endswith("." + h) for h in LISTING_HOSTS
    ):
        try:
            return normalize_domain(lead.canonical_url)
        except ValueError:
            pass
    blob = f"{lead.description}\n{lead.excerpt or ''}"
    for token in blob.split():
        if not token.startswith("http"):
            continue
        cleaned = token.rstrip(".,);\"'")
        try:
            domain = normalize_domain(cleaned)
        except ValueError:
            continue
        h = listing_host(cleaned)
        if h and h not in LISTING_HOSTS:
            return domain
    return None


def find_company_for_domain(session: Session, domain: str) -> Company | None:
    return session.scalar(select(Company).where(Company.domain == domain))
