"""Curated Discover keyword / exclude suggestions for the UI."""

from __future__ import annotations

from typing import Any

# Grouped include terms — matched against feed title/summary/link (case-insensitive).
KEYWORD_GROUPS: dict[str, list[str]] = {
    "Industries": [
        "logistics",
        "manufacturing",
        "healthcare",
        "fintech",
        "saas",
        "software",
        "retail",
        "ecommerce",
        "professional services",
        "warehouse",
        "supply chain",
    ],
    "What you sell / build": [
        "AI automation",
        "agentic AI",
        "SaaS",
        "API",
        "integrations",
        "RAG",
        "data platform",
        "modernization",
        "full-stack",
        "backend",
        "search",
    ],
    "Project / change signals": [
        "launches",
        "launch",
        "expansion",
        "opens",
        "funding",
        "raises",
        "series",
        "acquisition",
        "migration",
        "platform",
        "digital transformation",
        "automation",
    ],
}

EXCLUDE_GROUPS: dict[str, list[str]] = {
    "Hiring / jobs (noise for B2B projects)": [
        "hiring",
        "we're hiring",
        "careers",
        "jobs",
        "job opening",
        "recruiting",
        "staffing",
    ],
    "Other noise": [
        "newsletter",
        "podcast",
        "webinar replay",
        "giveaway",
        "black friday",
    ],
}

# Named presets → default include/exclude lists (still editable via checkboxes).
DISCOVER_PRESETS: dict[str, dict[str, Any]] = {
    "balanced": {
        "label": "Balanced — industries + skip hiring noise",
        "keywords": [
            "logistics",
            "manufacturing",
            "healthcare",
            "fintech",
            "saas",
            "warehouse",
            "AI automation",
            "SaaS",
            "integrations",
        ],
        "exclude_keywords": ["hiring", "careers", "jobs", "recruiting"],
        "use_profile_industries_as_keywords": True,
    },
    "project_signals": {
        "label": "Project signals — launches, funding, expansion",
        "keywords": [
            "launches",
            "launch",
            "expansion",
            "funding",
            "raises",
            "migration",
            "automation",
            "platform",
            "digital transformation",
        ],
        "exclude_keywords": ["hiring", "careers", "jobs", "newsletter", "podcast"],
        "use_profile_industries_as_keywords": True,
    },
    "ai_software": {
        "label": "AI / software buyers",
        "keywords": [
            "AI automation",
            "agentic AI",
            "SaaS",
            "API",
            "RAG",
            "data platform",
            "software",
            "saas",
            "integrations",
        ],
        "exclude_keywords": ["hiring", "careers", "jobs"],
        "use_profile_industries_as_keywords": False,
    },
    "open": {
        "label": "Open — no keyword filter (only excludes + social skip)",
        "keywords": [],
        "exclude_keywords": ["hiring", "careers", "jobs", "recruiting"],
        "use_profile_industries_as_keywords": False,
    },
    "custom": {
        "label": "Custom — use the choices below",
        "keywords": None,
        "exclude_keywords": None,
        "use_profile_industries_as_keywords": None,
    },
}


def all_keyword_suggestions() -> list[str]:
    out: list[str] = []
    for items in KEYWORD_GROUPS.values():
        out.extend(items)
    return out


def all_exclude_suggestions() -> list[str]:
    out: list[str] = []
    for items in EXCLUDE_GROUPS.values():
        out.extend(items)
    return out


def preset_choices() -> list[tuple[str, str]]:
    return [(key, spec["label"]) for key, spec in DISCOVER_PRESETS.items()]


# Curated free public feeds for the Discover dropdown (operator can still enter custom).
FEED_SUGGESTIONS: list[dict[str, str]] = [
    {
        "id": "tc",
        "group": "Tech / product news",
        "label": "TechCrunch",
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "kind": "rss",
    },
    {
        "id": "verge",
        "group": "Tech / product news",
        "label": "The Verge",
        "name": "The Verge",
        "url": "https://www.theverge.com/rss/index.xml",
        "kind": "rss",
    },
    {
        "id": "mittr",
        "group": "Tech / product news",
        "label": "MIT Technology Review",
        "name": "MIT Technology Review",
        "url": "https://www.technologyreview.com/feed/",
        "kind": "rss",
    },
    {
        "id": "hn",
        "group": "Tech / product news",
        "label": "Hacker News (frontpage)",
        "name": "Hacker News",
        "url": "https://hnrss.org/frontpage",
        "kind": "rss",
    },
    {
        "id": "bbc_biz",
        "group": "Business / industry",
        "label": "BBC Business",
        "name": "BBC Business",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "kind": "rss",
    },
    {
        "id": "ft_companies",
        "group": "Business / industry",
        "label": "Financial Times — Companies (free RSS)",
        "name": "FT Companies",
        "url": "https://www.ft.com/companies?format=rss",
        "kind": "rss",
    },
    {
        "id": "stripe",
        "group": "Company blogs / engineering",
        "label": "Stripe engineering blog",
        "name": "Stripe engineering blog",
        "url": "https://stripe.com/blog/feed.rss",
        "kind": "rss",
    },
    {
        "id": "github_blog",
        "group": "Company blogs / engineering",
        "label": "GitHub Blog",
        "name": "GitHub Blog",
        "url": "https://github.blog/feed/",
        "kind": "rss",
    },
    {
        "id": "gh_cli",
        "group": "GitHub releases (Atom)",
        "label": "cli/cli releases",
        "name": "GitHub CLI releases",
        "url": "https://github.com/cli/cli/releases.atom",
        "kind": "github_releases",
    },
    {
        "id": "gh_ollama",
        "group": "GitHub releases (Atom)",
        "label": "ollama/ollama releases",
        "name": "Ollama releases",
        "url": "https://github.com/ollama/ollama/releases.atom",
        "kind": "github_releases",
    },
]


def feed_suggestions_by_group() -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for item in FEED_SUGGESTIONS:
        grouped.setdefault(item["group"], []).append(item)
    return grouped


def feed_suggestions_map() -> dict[str, dict[str, str]]:
    return {item["id"]: item for item in FEED_SUGGESTIONS}
