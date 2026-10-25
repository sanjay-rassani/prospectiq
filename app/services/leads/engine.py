"""Unified discovery engine: adapters → score → persist → optional company seed."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.lead import DiscoveryLead, IntentClass, LeadKind, LeadStatus
from app.services.discovery.seed import seed_targets
from app.services.fetcher import Fetcher
from app.services.leads.adapters import adapters_by_key, list_capabilities
from app.services.leads.adapters.base import ProgressFn, emit
from app.services.leads.filters import TargetingFilters
from app.services.leads.persist import (
    company_domain_from_lead,
    find_company_for_domain,
    persist_candidate,
)


@dataclass
class DiscoveryStats:
    sources_run: int = 0
    sources_skipped: int = 0
    sources_failed: int = 0
    candidates: int = 0
    created: int = 0
    updated: int = 0
    duplicates: int = 0
    rejected_kept: int = 0
    filtered: int = 0
    seeded: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {
            "sources_run": self.sources_run,
            "sources_skipped": self.sources_skipped,
            "sources_failed": self.sources_failed,
            "candidates": self.candidates,
            "created": self.created,
            "updated": self.updated,
            "duplicates": self.duplicates,
            "filtered": self.filtered,
            "seeded": self.seeded,
            "errors": len(self.errors),
        }


def run_lead_discovery(
    session: Session,
    filters: TargetingFilters,
    *,
    fetcher: Fetcher | None = None,
    settings: Settings | None = None,
    on_progress: ProgressFn | None = None,
    seed_companies: bool | None = None,
) -> DiscoveryStats:
    settings = settings or get_settings()
    stats = DiscoveryStats()
    owns = fetcher is None
    fetcher = fetcher or Fetcher()
    do_seed = filters.seed_new_links if seed_companies is None else seed_companies
    registry = adapters_by_key()
    try:
        caps = {c.key: c for c in list_capabilities(settings)}
        enabled = [k for k in filters.enabled_sources if k in registry]
        emit(on_progress, "info", f"Discovery starting — {len(enabled)} source(s) selected")
        emit(on_progress, "info", _filters_summary(filters, caps))
        for key in [c.key for c in list_capabilities(settings)]:
            cap = caps[key]
            adapter = registry[key]
            if key not in filters.enabled_sources:
                continue
            if cap.availability == "restricted":
                emit(on_progress, "warn", f"{cap.label}: restricted — {cap.limitations}")
                stats.sources_skipped += 1
                continue
            if cap.availability == "optional_config":
                emit(
                    on_progress,
                    "warn",
                    f"{cap.label}: not configured ({cap.requires_config})",
                )
                stats.sources_skipped += 1
                continue
            emit(on_progress, "info", f"Searching {cap.label}…")
            try:
                raws = adapter.search(
                    session=session,
                    filters=filters,
                    fetcher=fetcher,
                    settings=settings,
                    on_progress=on_progress,
                    limit=filters.max_per_source,
                )
            except Exception as exc:  # noqa: BLE001
                stats.sources_failed += 1
                stats.errors.append(f"{cap.label}: {exc}")
                emit(on_progress, "error", f"{cap.label} failed: {exc}")
                continue
            stats.sources_run += 1
            stats.candidates += len(raws)
            for raw in raws:
                lead, action = persist_candidate(session, raw, filters)
                if action == "created" and lead is not None:
                    stats.created += 1
                    emit(
                        on_progress,
                        "ok",
                        f"{lead.intent_class} · {lead.title[:80]} ({int(lead.relevance_score)})",
                    )
                    if do_seed:
                        _maybe_seed(session, lead, filters, fetcher, stats, on_progress)
                elif action == "updated":
                    stats.updated += 1
                    stats.duplicates += 1
                elif action == "rejected_kept":
                    stats.rejected_kept += 1
                    stats.duplicates += 1
                else:
                    stats.filtered += 1
        emit(
            on_progress,
            "info",
            (
                f"Summary: {stats.created} new, {stats.updated} updated, "
                f"{stats.filtered} below threshold, {stats.seeded} saved to companies, "
                f"{stats.sources_failed} source error(s)"
            ),
        )
        return stats
    finally:
        if owns:
            fetcher.close()


def _maybe_seed(
    session: Session,
    lead: DiscoveryLead,
    filters: TargetingFilters,
    fetcher: Fetcher,
    stats: DiscoveryStats,
    on_progress: ProgressFn | None,
) -> None:
    if lead.intent_class == IntentClass.LOW_RELEVANCE.value:
        return
    if lead.lead_kind == LeadKind.PROJECT.value and listing_is_project_host(lead.canonical_url):
        return
    domain = company_domain_from_lead(lead)
    if not domain:
        return
    existing = find_company_for_domain(session, domain)
    if existing is not None:
        lead.company_id = existing.id
        if lead.status == LeadStatus.NEW.value:
            lead.status = LeadStatus.SAVED.value
        session.flush()
        return
    if filters.only_unknown_domains is False or existing is None:
        try:
            outcomes = seed_targets(session, f"https://{domain}", fetcher=fetcher)
        except ValueError as exc:
            emit(on_progress, "warn", f"Could not seed {domain}: {exc}")
            return
        if outcomes:
            lead.company_id = outcomes[0].company.id
            lead.status = LeadStatus.SAVED.value
            stats.seeded += 1
            emit(
                on_progress,
                "ok",
                f"Saved to companies: {outcomes[0].company.name} ({domain})",
            )
            session.flush()


def listing_is_project_host(url: str) -> bool:
    from app.services.leads.persist import LISTING_HOSTS, listing_host

    host = listing_host(url)
    return host in LISTING_HOSTS or any(host.endswith("." + h) for h in LISTING_HOSTS)


def _filters_summary(filters: TargetingFilters, caps: dict[str, object]) -> str:
    """Short line so the operator can confirm Run used the selected filters."""
    labels: list[str] = []
    for key in filters.enabled_sources:
        cap = caps.get(key)
        labels.append(getattr(cap, "label", key) if cap is not None else key)
    bits = [
        "Applying filters: sources=" + (", ".join(labels) if labels else "(none)"),
        f"min score={filters.min_relevance}",
    ]
    if filters.max_age_days > 0:
        bits.append(f"max age={filters.max_age_days}d")
    else:
        bits.append("max age=any")
    if filters.geographies:
        geo = ", ".join(filters.geographies[:6])
        if len(filters.geographies) > 6:
            geo += f" (+{len(filters.geographies) - 6})"
        bits.append(f"locations={geo}")
    if filters.include_remote:
        bits.append("remote allowed")
    if filters.required_keywords:
        bits.append("must include=" + ", ".join(filters.required_keywords[:6]))
    if filters.services:
        bits.append(f"services={len(filters.services)}")
    if filters.industries:
        bits.append(f"industries={len(filters.industries)} ({filters.industry_mode})")
    if filters.search_engines and "searxng" in filters.enabled_sources:
        bits.append("engines=" + ", ".join(filters.search_engines[:5]))
    return " · ".join(bits)
