"""Lead-source adapters — permitted public / operator-configured sources only."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.services.leads.adapters.base import AdapterCapability, LeadAdapter
from app.services.leads.adapters.contracts_uk import ContractsUkAdapter
from app.services.leads.adapters.custom_sources import CustomSourcesAdapter
from app.services.leads.adapters.github_issues import GitHubIssuesAdapter
from app.services.leads.adapters.hackernews import HackerNewsAdapter
from app.services.leads.adapters.rss_source import RssFeedsAdapter
from app.services.leads.adapters.searxng import SearxngAdapter


def all_adapters() -> list[LeadAdapter]:
    return [
        HackerNewsAdapter(),
        ContractsUkAdapter(),
        SearxngAdapter(),
        GitHubIssuesAdapter(),
        RssFeedsAdapter(),
        CustomSourcesAdapter(),
    ]


def list_capabilities(settings: Settings | None = None) -> list[AdapterCapability]:
    settings = settings or get_settings()
    caps = [a.capability(settings) for a in all_adapters()]
    caps.sort(key=lambda c: (c.priority, c.label))
    return caps


def adapters_by_key() -> dict[str, LeadAdapter]:
    return {a.key: a for a in all_adapters()}
