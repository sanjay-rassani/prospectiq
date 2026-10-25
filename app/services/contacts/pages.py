"""Discover candidate people-page URLs for a company (permitted paths only)."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from app.models import Company, SourceSnapshot
from app.services.buyers.guardrails import is_blocked_fetch_host, is_permitted_people_page

_CANDIDATE_PATHS = (
    "/",  # Homepage often lists founders / leadership
    "/about",
    "/about-us",
    "/about/team",
    "/about/leadership",
    "/team",
    "/our-team",
    "/our-people",
    "/people",
    "/leadership",
    "/management",
    "/contact",
    "/contact-us",
    "/company",
    "/company/about",
    "/company/team",
    "/who-we-are",
    "/meet-the-team",
    "/staff",
    "/executives",
    "/founders",
    "/founder",
    "/board",
    "/crew",
    "/directory",
    "/bios",
    "/partners",
    "/impressum",
    "/imprint",
)

_PEOPLE_PATH_HINTS = (
    "/team",
    "/about",
    "/people",
    "/leadership",
    "/contact",
    "/staff",
    "/founder",
    "/board",
    "/management",
    "/executives",
    "/crew",
    "/directory",
    "/bios",
    "/impressum",
    "/imprint",
    "/partners",
)

_HREF_RE = re.compile(
    r"""(?:href\s*=\s*["']([^"']+)["']|(https?://[^\s<>"')]+))""",
    re.IGNORECASE,
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
    company_host = (urlparse(base).hostname or company.domain or "").casefold()

    def add(url: str, *, force: bool = False) -> None:
        url = url.strip()
        if not url or is_blocked_fetch_host(url):
            return
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return
        host = (parsed.hostname or "").casefold()
        if company_host and host and company_host not in host and host not in company_host:
            # Stay on the company site (and common www./apex variants).
            return
        key = url.casefold().rstrip("/")
        if key in seen:
            return
        path = (parsed.path or "").casefold()
        if path in ("", "/"):
            pass  # homepage always allowed as a contact source
        elif not force and not is_permitted_people_page(url):
            if not any(
                path.rstrip("/") == p or path.startswith(p + "/") for p in _CANDIDATE_PATHS
            ):
                return
        seen.add(key)
        found.append(url)

    for path in _CANDIDATE_PATHS:
        if path == "/":
            add(base.rstrip("/") + "/")
        else:
            add(urljoin(base + "/", path.lstrip("/")))

    for snap in snapshots or []:
        if is_permitted_people_page(snap.url) or urlparse(snap.url).path in ("", "/"):
            add(snap.url)
        for link in _links_from_text(snap.text or "", base=base):
            path = (urlparse(link).path or "").casefold()
            if any(frag in path for frag in _PEOPLE_PATH_HINTS):
                add(link)

    return found


def harvest_people_links_from_text(text: str, *, base_url: str) -> list[str]:
    """Extra team/about links discovered after fetching a page (second-pass expansion)."""
    out: list[str] = []
    seen: set[str] = set()
    for link in _links_from_text(text or "", base=base_url):
        path = (urlparse(link).path or "").casefold()
        if not any(frag in path for frag in _PEOPLE_PATH_HINTS):
            continue
        key = link.casefold().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(link)
    return out


def _links_from_text(text: str, *, base: str) -> list[str]:
    links: list[str] = []
    for match in _HREF_RE.finditer(text or ""):
        raw = (match.group(1) or match.group(2) or "").strip()
        if not raw or raw.startswith("#") or raw.lower().startswith("mailto:"):
            continue
        cleaned = raw.rstrip(".,);\"'")
        absolute = urljoin(base + "/", cleaned)
        if absolute.startswith("http"):
            links.append(absolute)
    return links
