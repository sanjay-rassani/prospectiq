"""Deterministic buying-intent classification and relevance scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.models.lead import IntentClass, LeadKind
from app.services.leads.filters import SERVICE_QUERY_TERMS, TargetingFilters

HIGH_INTENT_PHRASES: tuple[str, ...] = (
    "looking for",
    "looking for a",
    "need a developer",
    "need an app",
    "need a website",
    "seeking freelancer",
    "seeking a developer",
    "hire a developer",
    "rfp",
    "rfq",
    "request for proposal",
    "tender",
    "procurement",
    "call for tenders",
    "build me",
    "build an app",
    "custom software",
    "software needed",
    "integrate an llm",
    "automate",
    "automation needed",
    "replace spreadsheet",
    "legacy modernization",
)

EMERGING_PHRASES: tuple[str, ...] = (
    "digital transformation",
    "launching",
    "raises",
    "series a",
    "series b",
    "expansion",
    "migrating",
    "modernizing",
    "new platform",
    "opened a",
)

EDU_PHRASES: tuple[str, ...] = (
    "university",
    "college",
    "school",
    "campus",
    "edtech",
    "student",
    "research institute",
    "laboratory",
)

TECH_REQUIREMENTS: tuple[str, ...] = (
    "api",
    "saas",
    "rag",
    "llm",
    "ai",
    "automation",
    "integration",
    "backend",
    "mobile",
    "devops",
    "data pipeline",
    "crm",
    "erp",
    "workflow",
)


@dataclass
class ScoreResult:
    intent_class: str
    lead_kind: str
    relevance: float
    reasons: list[str] = field(default_factory=list)
    matched: dict[str, list[str]] = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)
    intent_indicators: list[str] = field(default_factory=list)


def _blob(*parts: str | None) -> str:
    return "\n".join(p for p in parts if p).casefold()


def score_candidate(
    *,
    title: str,
    description: str,
    url: str,
    source_category: str,
    filters: TargetingFilters,
    published_at: datetime | None = None,
    location: str | None = None,
    budget_text: str | None = None,
) -> ScoreResult:
    text = _blob(title, description, url)
    reasons: list[str] = []
    matched: dict[str, list[str]] = {"services": [], "industries": [], "keywords": []}
    score = 15.0

    if any(ex.strip() and ex.strip().casefold() in text for ex in filters.exclude_keywords):
        return ScoreResult(
            intent_class=IntentClass.LOW_RELEVANCE.value,
            lead_kind=LeadKind.OTHER.value,
            relevance=0,
            reasons=["Matched an excluded keyword"],
        )

    missing_required = [
        kw for kw in filters.required_keywords if kw.strip() and kw.casefold() not in text
    ]
    if missing_required:
        return ScoreResult(
            intent_class=IntentClass.LOW_RELEVANCE.value,
            lead_kind=LeadKind.OTHER.value,
            relevance=5,
            reasons=[f"Missing required keyword: {missing_required[0]}"],
        )

    intent_hits = [p for p in HIGH_INTENT_PHRASES if p in text]
    emerging_hits = [p for p in EMERGING_PHRASES if p in text]
    reqs = [t for t in TECH_REQUIREMENTS if t in text]

    for sid in filters.services:
        terms = SERVICE_QUERY_TERMS.get(sid, (sid,))
        if any(term.casefold() in text for term in terms):
            matched["services"].append(sid)
    if matched["services"]:
        score += 12 + 6 * min(len(matched["services"]), 3)
        reasons.append("Matches selected services: " + ", ".join(matched["services"][:4]))
    elif filters.services:
        score -= 8
        reasons.append("No selected-service terms observed")

    industry_hits: list[str] = []
    for ind in filters.industries:
        needle = ind.replace("_", " ").casefold()
        if needle and needle in text:
            industry_hits.append(ind)
    matched["industries"] = industry_hits
    if industry_hits:
        score += 12
        reasons.append("Industry terms present: " + ", ".join(industry_hits[:4]))
    elif filters.industries and filters.industry_mode == "strict":
        return ScoreResult(
            intent_class=IntentClass.LOW_RELEVANCE.value,
            lead_kind=LeadKind.OTHER.value,
            relevance=10,
            reasons=["Strict industry filter: no industry terms on the listing"],
        )
    elif filters.industries:
        score -= 4
        reasons.append("Industry match is inferred, not explicit")

    for kw in filters.optional_keywords:
        if kw.strip() and kw.casefold() in text:
            matched["keywords"].append(kw)
    if matched["keywords"]:
        score += min(12, 4 * len(matched["keywords"]))
        reasons.append("Optional keywords matched")

    geo_hit = False
    if filters.geographies:
        for geo in filters.geographies:
            if geo.strip() and geo.casefold() in text:
                geo_hit = True
                break
        if location and any(g.casefold() in location.casefold() for g in filters.geographies):
            geo_hit = True
    if geo_hit:
        score += 8
        reasons.append("Geography mentioned")
    elif filters.geographies and not filters.include_remote:
        score -= 15
        reasons.append("No geography match and remote not allowed")
    elif filters.include_remote:
        reasons.append("Remote/unknown location allowed")

    if budget_text:
        score += 5
        reasons.append("Public budget/value mentioned")

    if published_at:
        age_days = (datetime.now(UTC) - published_at).total_seconds() / 86400
        if age_days <= 14:
            score += 8
            reasons.append("Listing is fresh (≤14 days)")
        elif age_days > 180:
            score -= 10
            reasons.append("Listing looks stale (>180 days)")

    edu = any(p in text for p in EDU_PHRASES)
    if intent_hits:
        intent = IntentClass.HIGH_INTENT.value
        score += 28 if filters.prefer_high_intent else 18
        reasons.append("Explicit buying-intent language: " + ", ".join(intent_hits[:3]))
        kind = LeadKind.PROJECT.value
    elif emerging_hits:
        intent = IntentClass.EMERGING.value
        score += 12
        reasons.append("Emerging-need language: " + ", ".join(emerging_hits[:3]))
        kind = LeadKind.COMPANY.value
    elif source_category == "p2_business":
        intent = IntentClass.POTENTIAL.value
        score += 6
        reasons.append("Company/directory match without an explicit request")
        kind = LeadKind.COMPANY.value
    else:
        intent = IntentClass.LOW_RELEVANCE.value
        reasons.append("Weak evidence of a current technical need")
        kind = LeadKind.OTHER.value

    if edu and ("school" in filters.lead_types or "research" in filters.lead_types):
        kind = LeadKind.INSTITUTION.value
        score += 6
        reasons.append("Education/research institution language")
    if "government" in filters.lead_types and any(
        p in text for p in ("tender", "procurement", "government", "public sector")
    ):
        kind = LeadKind.INSTITUTION.value

    if source_category == "p1_intent" and intent == IntentClass.HIGH_INTENT.value:
        score += 6

    score = max(0.0, min(100.0, score))
    if score < 20 and intent != IntentClass.HIGH_INTENT.value:
        intent = IntentClass.LOW_RELEVANCE.value

    return ScoreResult(
        intent_class=intent,
        lead_kind=kind,
        relevance=round(score, 1),
        reasons=reasons,
        matched=matched,
        requirements=reqs,
        intent_indicators=intent_hits or emerging_hits,
    )
