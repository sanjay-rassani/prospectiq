"""Targeting filters and query generation for filter-driven discovery."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from app.services.scoring.profile import DiscoverPrefs, OperatorProfile

LEAD_TYPES: list[tuple[str, str]] = [
    ("project_request", "People / businesses posting technology projects"),
    ("company_seeking_dev", "Companies seeking software development"),
    ("startup", "Startups"),
    ("sme", "Small and medium-sized businesses"),
    ("enterprise", "Enterprise companies"),
    ("school", "Schools and universities"),
    ("research", "Research institutions"),
    ("government", "Government and nonprofit organizations"),
    ("other", "Other organizations"),
]

SERVICES: list[tuple[str, str]] = [
    ("backend_api", "Backend and API development"),
    ("fullstack", "Full-stack web development"),
    ("saas", "SaaS development"),
    ("mobile", "Mobile applications"),
    ("ai_ml", "AI and machine learning"),
    ("llm_rag", "LLM and RAG solutions"),
    ("ai_agents", "AI agent development"),
    ("automation", "Workflow and business process automation"),
    ("data_eng", "Data engineering and analytics"),
    ("devops", "Cloud infrastructure and DevOps"),
    ("modernization", "Legacy system modernization"),
    ("integrations", "Third-party integrations"),
    ("custom_software", "Custom software development"),
]

INDUSTRIES: list[tuple[str, str]] = [
    ("healthcare", "Healthcare / healthtech"),
    ("fintech", "Financial services / fintech"),
    ("education", "Education"),
    ("ecommerce", "E-commerce"),
    ("saas", "SaaS / software"),
    ("manufacturing", "Manufacturing"),
    ("logistics", "Logistics"),
    ("real_estate", "Real estate / property"),
    ("professional_services", "Professional services / agencies"),
    ("government", "Government / public sector"),
    ("nonprofit", "Nonprofit"),
]

SERVICE_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    "backend_api": ("backend", "API", "REST", "integrations"),
    "fullstack": ("full-stack", "web application", "web app"),
    "saas": ("SaaS", "software as a service"),
    "mobile": ("mobile app", "iOS", "Android"),
    "ai_ml": ("machine learning", "AI", "ML model"),
    "llm_rag": ("LLM", "RAG", "ChatGPT", "language model"),
    "ai_agents": ("AI agent", "agentic", "autonomous agent"),
    "automation": ("automation", "workflow", "RPA", "automate"),
    "data_eng": ("data engineering", "analytics", "ETL", "data pipeline"),
    "devops": ("DevOps", "cloud infrastructure", "Kubernetes"),
    "modernization": ("legacy modernization", "migrate", "rewrite"),
    "integrations": ("integration", "API integration", "connect systems"),
    "custom_software": ("custom software", "bespoke software", "build an app"),
}

INTENT_QUERY_STEMS: tuple[str, ...] = (
    "looking for developer",
    "need a software developer",
    "seeking freelance developer",
    "RFP software",
    "custom software needed",
    "automate workflow",
    "AI integration",
)


class TargetingFilters(BaseModel):
    """Operator targeting used to query adapters and score candidates."""

    lead_types: list[str] = Field(
        default_factory=lambda: ["project_request", "company_seeking_dev", "startup", "sme"]
    )
    services: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    industry_mode: str = "flexible"
    geographies: list[str] = Field(default_factory=list)
    include_remote: bool = True
    required_keywords: list[str] = Field(default_factory=list)
    optional_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    min_relevance: int = 30
    enabled_sources: list[str] = Field(
        default_factory=lambda: ["hackernews", "contracts_uk", "rss_feeds"]
    )
    prefer_high_intent: bool = True
    budget_min: float | None = None
    budget_max: float | None = None
    budget_currency: str = ""
    seed_new_links: bool = True
    skip_social_hosts: bool = True
    only_unknown_domains: bool = True
    max_per_source: int = 20

    @field_validator("industry_mode")
    @classmethod
    def _mode(cls, value: str) -> str:
        return value if value in {"strict", "flexible"} else "flexible"

    @field_validator("min_relevance")
    @classmethod
    def _clamp_relevance(cls, value: int) -> int:
        return max(0, min(int(value), 100))

    @field_validator("max_per_source")
    @classmethod
    def _clamp_max(cls, value: int) -> int:
        return max(1, min(int(value), 50))


def filters_from_prefs(
    prefs: DiscoverPrefs, profile: OperatorProfile
) -> TargetingFilters:
    optional = list(prefs.optional_keywords or [])
    if not optional:
        optional = list(prefs.keywords or [])
    industries = list(prefs.industries or [])
    if not industries and prefs.use_profile_industries_as_keywords:
        industries = [i.strip().casefold().replace(" ", "_") for i in profile.target_industries]
        industries = [i for i in industries if i]
    geos = list(prefs.geographies or [])
    if not geos:
        geos = [g.strip() for g in profile.target_regions if g.strip()]
    sources = list(prefs.enabled_sources or [])
    if not sources:
        sources = ["hackernews", "contracts_uk", "rss_feeds"]
    return TargetingFilters(
        lead_types=list(prefs.lead_types or ["project_request", "company_seeking_dev"]),
        services=list(prefs.services or []),
        industries=industries,
        industry_mode=prefs.industry_mode or "flexible",
        geographies=geos,
        include_remote=bool(prefs.include_remote),
        required_keywords=list(prefs.required_keywords or []),
        optional_keywords=optional,
        exclude_keywords=list(prefs.exclude_keywords or []),
        min_relevance=int(prefs.min_relevance or 30),
        enabled_sources=sources,
        prefer_high_intent=bool(prefs.prefer_high_intent),
        budget_min=prefs.budget_min,
        budget_max=prefs.budget_max,
        budget_currency=prefs.budget_currency or "",
        seed_new_links=bool(prefs.seed_new_links),
        skip_social_hosts=bool(prefs.skip_social_hosts),
        only_unknown_domains=bool(prefs.only_unknown_domains),
        max_per_source=int(prefs.max_new_entries_per_feed or 20),
    )


@dataclass(frozen=True)
class SearchQuery:
    text: str
    intent: str  # high_intent | company | education | general
    extra: dict[str, str] = field(default_factory=dict)


def build_search_queries(filters: TargetingFilters, *, limit: int = 8) -> list[SearchQuery]:
    """Turn targeting into a small set of source-agnostic search phrases."""
    queries: list[SearchQuery] = []
    seen: set[str] = set()

    def add(text: str, intent: str) -> None:
        cleaned = " ".join(text.split()).strip()
        key = cleaned.casefold()
        if not cleaned or key in seen or len(queries) >= limit:
            return
        seen.add(key)
        queries.append(SearchQuery(text=cleaned, intent=intent))

    service_terms: list[str] = []
    for sid in filters.services:
        service_terms.extend(SERVICE_QUERY_TERMS.get(sid, (sid,)))
    if not service_terms:
        service_terms = ["software development", "AI automation", "custom software"]

    if "project_request" in filters.lead_types or "company_seeking_dev" in filters.lead_types:
        add(f"{service_terms[0]} {INTENT_QUERY_STEMS[0]}", "high_intent")
        add(f"need {service_terms[0]}", "high_intent")
        add("RFP software development", "high_intent")
        add("looking for freelance developer to build app", "high_intent")

    for kw in filters.required_keywords:
        add(kw, "high_intent")
    for kw in filters.optional_keywords[:4]:
        add(kw, "general")

    if any(t in filters.lead_types for t in ("startup", "sme", "enterprise")):
        industry = filters.industries[0].replace("_", " ") if filters.industries else "SaaS"
        add(f"{industry} digital transformation", "company")
        add(f"{industry} software modernization", "company")

    if any(t in filters.lead_types for t in ("school", "research")):
        add("university software tender", "education")
        add("school digital transformation RFP", "education")

    if "government" in filters.lead_types:
        add("public sector software procurement", "high_intent")
        add("government AI automation tender", "high_intent")

    if not queries:
        add("custom software development", "general")
    return queries
