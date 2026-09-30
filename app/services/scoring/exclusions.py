"""Exclusion rules (task P5-8). Evaluated before scoring promotion."""

from __future__ import annotations

from app.models import Company
from app.services.scoring.profile import OperatorProfile


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


def _token_in(haystack: str, needles: list[str]) -> str | None:
    h = haystack.casefold()
    for needle in needles:
        n = needle.casefold().strip()
        if n and n in h:
            return needle
    return None


def exclusion_reason(company: Company, profile: OperatorProfile) -> str | None:
    """Return a human reason if this company must not be approached, else None."""
    domain = _norm(company.domain)
    if domain in {_norm(d) for d in profile.do_not_contact_domains}:
        return f"do-not-contact domain: {company.domain}"

    facts = company.facts_json or {}
    if facts.get("is_recruiter_or_staffing"):
        return "recruiter/staffing business (excluded target)"
    if facts.get("is_job_or_careers_page"):
        return "job/careers page (employment lead, not project work)"

    industry = _norm(str(facts.get("industry") or company.industry or ""))
    hit = _token_in(industry, profile.excluded_industries)
    if hit:
        return f"excluded industry match: {hit}"

    geography_bits: list[str] = []
    if isinstance(facts.get("geography"), list):
        geography_bits.extend(str(g) for g in facts["geography"])
    if company.geography:
        geography_bits.append(company.geography)
    geo = " ".join(geography_bits)
    hit = _token_in(geo, profile.excluded_geographies)
    if hit:
        return f"excluded geography match: {hit}"

    return None
