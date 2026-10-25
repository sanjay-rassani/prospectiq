"""Adapter registry: which discovery sources exist and whether they are enabled."""

from __future__ import annotations

from dataclasses import dataclass

from app.models import AdapterKind


@dataclass(frozen=True)
class AdapterSpec:
    kind: str
    label: str
    description: str
    enabled_by_default: bool = True
    requires_playwright: bool = False


ADAPTER_REGISTRY: dict[str, AdapterSpec] = {
    AdapterKind.MANUAL_SEED.value: AdapterSpec(
        kind=AdapterKind.MANUAL_SEED.value,
        label="Manual seed",
        description="Operator pastes domains/URLs. Always available.",
    ),
    AdapterKind.COMPANY_PAGE.value: AdapterSpec(
        kind=AdapterKind.COMPANY_PAGE.value,
        label="Company page refresh",
        description="Re-fetch known company URLs on the adaptive cadence.",
    ),
    AdapterKind.RSS.value: AdapterSpec(
        kind=AdapterKind.RSS.value,
        label="RSS / Atom",
        description=(
            "Primary auto-discovery: poll feeds, dedupe by entry id/link, "
            "seed companies from item links into the same pipeline as manual seed."
        ),
    ),
    AdapterKind.GITHUB_RELEASES.value: AdapterSpec(
        kind=AdapterKind.GITHUB_RELEASES.value,
        label="GitHub releases",
        description="Optional public releases Atom feed for a repo (permitted technical source).",
        enabled_by_default=False,
    ),
    AdapterKind.CHANGELOG.value: AdapterSpec(
        kind=AdapterKind.CHANGELOG.value,
        label="Changelog page",
        description="Optional public changelog/news URL treated like a company page.",
        enabled_by_default=False,
    ),
    # Free-only policy (D-26): no paid search APIs; no Google/LinkedIn scrape or login bots.
    "web_search": AdapterSpec(
        kind="web_search",
        label="Discover lead sources",
        description=(
            "Filter-driven discovery on Discover: Hacker News, UK Contracts Finder, "
            "GitHub issues, RSS, optional SearXNG (+ engine picker), and custom feeds. "
            "Configure sources on Discover — never paid search APIs, never scrape marketplaces."
        ),
        enabled_by_default=True,
    ),
}


def list_adapters() -> list[AdapterSpec]:
    return list(ADAPTER_REGISTRY.values())


def get_adapter(kind: str) -> AdapterSpec | None:
    return ADAPTER_REGISTRY.get(kind)
