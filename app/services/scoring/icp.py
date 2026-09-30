"""ICP Fit — company-level, timing-blind (spec §8.1, tasks P5-2/P5-3).

See INPUTS.md for the dimension definitions. This module must never import or read Signal
or Opportunity rows.
"""

from __future__ import annotations

from app.models import Company
from app.services.scoring.exclusions import exclusion_reason
from app.services.scoring.profile import OperatorProfile, get_operator_profile
from app.services.scoring.types import DimensionScore, ScoreResult, clamp, weighted_total

# Size → commercial maturity proxy. No signal/timing fields here by design.
_SIZE_SCORES = {
    "large": 90.0,
    "medium": 80.0,
    "small": 55.0,
    "solo": 25.0,
    "unclear": 35.0,
}

_CUSTOMER_SCORES = {
    "b2b": 90.0,
    "both": 75.0,
    "b2c": 40.0,
    "unclear": 45.0,
}


def _tokens(*parts: object) -> set[str]:
    out: set[str] = set()
    for part in parts:
        if part is None:
            continue
        if isinstance(part, list):
            for item in part:
                out |= _tokens(item)
            continue
        for tok in str(part).casefold().replace("/", " ").replace("-", " ").split():
            if len(tok) > 2:
                out.add(tok)
    return out


def _match_score(haystack: set[str], needles: list[str]) -> tuple[float, str]:
    if not needles:
        return 55.0, "no target list configured; neutral"
    hits = [n for n in needles if any(n.casefold() in h or h in n.casefold() for h in haystack)]
    if not hits and haystack:
        # Also allow substring match against joined text.
        joined = " ".join(haystack)
        hits = [n for n in needles if n.casefold() in joined]
    if not hits:
        return 25.0, "no overlap with target list"
    ratio = min(1.0, len(hits) / max(1, min(3, len(needles))))
    return 40.0 + 60.0 * ratio, f"matched: {', '.join(hits[:5])}"


def score_icp(
    company: Company,
    profile: OperatorProfile | None = None,
) -> ScoreResult:
    """Compute ICP Fit. Uses company facts only — never signals."""
    profile = profile or get_operator_profile()
    reason = exclusion_reason(company, profile)
    if reason:
        return ScoreResult(
            total=0.0,
            dimensions=[],
            excluded=True,
            exclusion_reason=reason,
        )

    facts = company.facts_json or {}
    industry = str(facts.get("industry") or company.industry or "")
    size = str(facts.get("size_hint") or company.size_hint or "unclear").casefold()
    customer = str(facts.get("customer_type") or "unclear").casefold()
    products = facts.get("products_or_services") or []
    tech = facts.get("technologies_mentioned") or []
    geography = facts.get("geography") or []
    if company.geography and not geography:
        geography = [company.geography]

    # --- business fit 30% ---
    ind_tokens = _tokens(industry)
    ind_score, ind_reason = _match_score(ind_tokens, profile.target_industries)
    excl_hit = next(
        (
            e
            for e in profile.excluded_industries
            if e.casefold() in industry.casefold()
        ),
        None,
    )
    if excl_hit:
        ind_score = 0.0
        ind_reason = f"excluded industry token: {excl_hit}"

    # --- ability to buy 25% ---
    size_score = _SIZE_SCORES.get(size, 35.0)
    cust_score = _CUSTOMER_SCORES.get(customer, 45.0)
    buy_score = clamp(0.6 * size_score + 0.4 * cust_score)
    buy_reason = f"size={size} ({size_score:.0f}), customer={customer} ({cust_score:.0f})"

    # --- outsourcing plausibility 20% ---
    out_score = 55.0
    out_bits = ["baseline"]
    if size == "solo":
        out_score -= 25
        out_bits.append("solo operator (harder to outsource)")
    if products:
        out_score += 20
        out_bits.append(f"{len(products)} named products/services")
    else:
        out_score -= 10
        out_bits.append("no named products/services")
    if "agency" in industry.casefold() or "consultancy" in industry.casefold():
        if profile.allow_agency_white_label:
            out_score = max(out_score, 50)
            out_bits.append("agency allowed for white-label")
        else:
            out_score = 15
            out_bits.append("agency excluded by profile")
    out_score = clamp(out_score)

    # --- solution-domain fit 15% ---
    domain_tokens = _tokens(products, tech, industry)
    cap_score, cap_reason = _match_score(
        domain_tokens, profile.capabilities + profile.preferred_solution_families
    )

    # --- decision-maker accessibility 10% ---
    geo_tokens = _tokens(geography)
    geo_score, geo_reason = _match_score(geo_tokens, profile.target_regions)
    if size in {"small", "medium"}:
        geo_score = clamp(geo_score + 10)
        geo_reason += "; SMB/mid-market size preferred"
    elif size == "large":
        geo_score = clamp(geo_score - 5)
        geo_reason += "; large orgs harder to reach cold"

    dimensions = [
        DimensionScore("business_fit", 0.30, ind_score, ind_reason),
        DimensionScore("ability_to_buy", 0.25, buy_score, buy_reason),
        DimensionScore("outsourcing_plausibility", 0.20, out_score, "; ".join(out_bits)),
        DimensionScore("solution_domain_fit", 0.15, cap_score, cap_reason),
        DimensionScore("decision_maker_accessibility", 0.10, geo_score, geo_reason),
    ]
    return ScoreResult(total=weighted_total(dimensions), dimensions=dimensions)
