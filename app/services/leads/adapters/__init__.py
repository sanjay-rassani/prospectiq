"""Lead-source adapters. Restricted sources are listed but never searched."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.services.leads.adapters.base import AdapterCapability, LeadAdapter
from app.services.leads.adapters.contracts_uk import ContractsUkAdapter
from app.services.leads.adapters.github_issues import GitHubIssuesAdapter
from app.services.leads.adapters.hackernews import HackerNewsAdapter
from app.services.leads.adapters.restricted import RestrictedAdapter
from app.services.leads.adapters.rss_source import RssFeedsAdapter
from app.services.leads.adapters.searxng import SearxngAdapter

_RESTRICTED = [
    RestrictedAdapter(
        key="upwork",
        label="Upwork",
        category="p1_intent",
        description="Freelance marketplace. Official API is partner-only.",
        limitations=(
            "No public search API for arbitrary prospecting. Import a listing URL "
            "manually or use an authorized integration if you obtain one."
        ),
        requires_config="Authorized Upwork API (not bundled)",
        priority=5,
    ),
    RestrictedAdapter(
        key="fiverr",
        label="Fiverr",
        category="p1_intent",
        description="Freelance marketplace. No documented public discovery API.",
        limitations="Automated listing harvest is not permitted. Paste a public URL to seed.",
        priority=6,
    ),
    RestrictedAdapter(
        key="linkedin",
        label="LinkedIn",
        category="p2_business",
        description="Never fetched. Store a URL only after manual research.",
        limitations="No scraping, no login automation, no unofficial APIs.",
        priority=99,
    ),
]


def all_adapters() -> list[LeadAdapter]:
    return [
        HackerNewsAdapter(),
        ContractsUkAdapter(),
        SearxngAdapter(),
        GitHubIssuesAdapter(),
        RssFeedsAdapter(),
        *_RESTRICTED,
    ]


def list_capabilities(settings: Settings | None = None) -> list[AdapterCapability]:
    settings = settings or get_settings()
    caps = [a.capability(settings) for a in all_adapters()]
    caps.sort(key=lambda c: (c.priority, c.label))
    return caps


def adapters_by_key() -> dict[str, LeadAdapter]:
    return {a.key: a for a in all_adapters()}
