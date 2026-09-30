"""Deterministic opportunity → buyer-role vocabulary from spec §9.1."""

from __future__ import annotations

from app.models import SolutionFamily

# Spec §9.1 maps opportunity kinds to likely buyer roles. Keys are our SolutionFamily
# values (spec §3.2). Agency white-label is handled as an industry overlay, not a family.
ROLE_MAP: dict[str, tuple[str, ...]] = {
    SolutionFamily.AGENTIC_AI_AUTOMATION.value: (
        "COO",
        "Head of Operations",
        "Operations Director",
        "Head of Support/CX",
        "CTO",
    ),
    SolutionFamily.CUSTOM_SOFTWARE_SAAS.value: (
        "Founder/CEO",
        "CPO/Product Lead",
        "CTO",
    ),
    SolutionFamily.INTEGRATIONS_APIS.value: (
        "CTO/Engineering",
        "Operations owner",
        "Product owner",
    ),
    SolutionFamily.BACKEND_DATA_SEARCH.value: (
        "CTO",
        "Head of Data/AI",
        "Product owner",
        "VP Engineering",
        "Head of Engineering",
    ),
    SolutionFamily.MODERNIZATION_SCALE.value: (
        "CTO",
        "VP Engineering",
        "Head of Engineering",
    ),
    SolutionFamily.FULL_STACK_PRODUCT.value: (
        "Founder/CEO",
        "CPO/Product Lead",
        "CTO",
    ),
}

AGENCY_ROLES: tuple[str, ...] = (
    "Founder",
    "Agency Owner",
    "Delivery/Technology Director",
)

_AGENCY_HINTS = ("agency", "consultancy", "consulting", "studio")


def is_agency_company(*, industry: str | None, description: str | None, name: str | None) -> bool:
    blob = " ".join(p for p in (industry, description, name) if p).casefold()
    return any(hint in blob for hint in _AGENCY_HINTS)


def roles_for_family(
    solution_family: str,
    *,
    industry: str | None = None,
    description: str | None = None,
    name: str | None = None,
) -> tuple[str, ...]:
    """Return the closed vocabulary for an opportunity (§9.1)."""
    base = ROLE_MAP.get(solution_family, ("COO", "CTO", "Founder/CEO"))
    if is_agency_company(industry=industry, description=description, name=name):
        # Spec §9.1 agency white-label row — prepend agency roles, keep family roles.
        seen: list[str] = []
        for role in (*AGENCY_ROLES, *base):
            if role not in seen:
                seen.append(role)
        return tuple(seen)
    return base


def all_known_roles() -> frozenset[str]:
    roles: set[str] = set(AGENCY_ROLES)
    for group in ROLE_MAP.values():
        roles.update(group)
    return frozenset(roles)


def normalize_to_vocabulary(candidate: str, allowed: tuple[str, ...]) -> str | None:
    """Map a free-form role string onto the closed vocabulary, or None if no match."""
    needle = _compact(candidate)
    if not needle:
        return None
    for role in allowed:
        if _compact(role) == needle:
            return role
    for role in allowed:
        compact_role = _compact(role)
        if needle in compact_role or compact_role in needle:
            return role
    # Token overlap: "Head of Ops" ↔ "Head of Operations"
    needle_tokens = set(_tokens(candidate))
    best: str | None = None
    best_score = 0
    for role in allowed:
        role_tokens = set(_tokens(role))
        score = len(needle_tokens & role_tokens)
        if score > best_score and score >= 2:
            best = role
            best_score = score
    return best


def _compact(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _tokens(value: str) -> list[str]:
    return [t for t in "".join(ch if ch.isalnum() else " " for ch in value.casefold()).split() if t]
