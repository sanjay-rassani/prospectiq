"""Discover candidate people-page URLs for a company (permitted paths only)."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from app.models import Company, SourceSnapshot
from app.services.buyers.guardrails import is_blocked_fetch_host, is_permitted_people_page

_CANDIDATE_PATHS = (
    "/about",
    "/about-us",
    "/team",
    "/our-team",
    "/our-people",
    "/people",
    "/leadership",
    "/management",
    "/contact",
    "/contact-us",
    "/company",
    "/who-we-are",
    "/meet-the-team",
    "/staff",
    "/executives",
)


def company_base_url(company: Company) -> str:
    if company.seed_url:
        parsed = urlparse(company.seed_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return f"https://{company.domain}"


def candidate_people_urls(
    company: Company,
    snapshots: list[SourceSnapshot] | None = None,
) -> list[str]:
    """Build a prioritized list of URLs likely to contain people, without fetching yet."""
    base = company_base_url(company)
    found: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        url = url.strip()
        if not url or is_blocked_fetch_host(url):
            return
        key = url.casefold().rstrip("/")
        if key in seen:
            return
        if not is_permitted_people_page(url) and urlparse(url).path not in ("", "/"):
            # Still allow exact candidate paths we generate.
            path = (urlparse(url).path or "").casefold()
            if not any(path.rstrip("/") == p or path.startswith(p + "/") for p in _CANDIDATE_PATHS):
                return
        seen.add(key)
        found.append(url)

    for path in _CANDIDATE_PATHS:
        add(urljoin(base + "/", path.lstrip("/")))

    for snap in snapshots or []:
        if is_permitted_people_page(snap.url):
            add(snap.url)
        # Pull internal links that look like people pages from snapshot text.
        people_frags = ("/team", "/about", "/people", "/leadership", "/contact")
        for token in (snap.text or "").split():
            if token.startswith("http") and any(
                frag in token.casefold() for frag in people_frags
            ):
                cleaned = token.rstrip(".,);\"'")
                host = urlparse(cleaned).hostname or ""
                if host and company.domain in host.casefold():
                    add(cleaned)

    return found
