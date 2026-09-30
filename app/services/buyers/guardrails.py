"""Hard guardrails for person discovery (spec §9.2 / P6-6).

Never scrape LinkedIn. Never invent or pattern-guess email addresses.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Fetching these hosts is forbidden. Storing a LinkedIn URL the operator pastes, or that
# already appears on a company page, is allowed — that is not scraping.
_BLOCKED_FETCH_HOSTS = (
    "linkedin.com",
    "www.linkedin.com",
    "uk.linkedin.com",
    "lnkd.in",
)

_PERMITTED_PATH_FRAGMENTS = (
    "/about",
    "/team",
    "/our-team",
    "/our-people",
    "/people",
    "/leadership",
    "/contact",
    "/company",
    "/who-we-are",
    "/meet-the-team",
    "/management",
)


class BuyerGuardrailError(ValueError):
    """Raised when an operation would cross the person-discovery boundary."""


def hostname(url: str) -> str:
    return (urlparse(url).hostname or "").casefold()


def is_blocked_fetch_host(url: str) -> bool:
    host = hostname(url)
    return any(host == blocked or host.endswith("." + blocked) for blocked in _BLOCKED_FETCH_HOSTS)


def assert_fetch_allowed(url: str) -> None:
    """Refuse to fetch LinkedIn (or similar) for person discovery."""
    if is_blocked_fetch_host(url):
        raise BuyerGuardrailError(
            f"Refusing to fetch {url!r}: LinkedIn and similar hosts are never scraped. "
            "Recommend a role and create a manual research task instead."
        )


def is_permitted_people_page(url: str) -> bool:
    """True when the URL looks like a public team/about/contact page on the company site."""
    if is_blocked_fetch_host(url):
        return False
    path = (urlparse(url).path or "/").casefold().rstrip("/") or "/"
    if path == "/":
        return False
    return any(fragment in path for fragment in _PERMITTED_PATH_FRAGMENTS)


def reject_guessed_email(*, name: str, domain: str, email: str | None) -> str | None:
    """Return email only when it is not an obvious name+domain invention.

    Finding an address that already appears on a permitted page is fine. Constructing
    first.last@domain from a name is forbidden (P6-6).
    """
    if not email:
        return None
    cleaned = email.strip().casefold()
    if "@" not in cleaned:
        return None
    _local, _, host = cleaned.partition("@")
    host = host.strip(".")
    domain_norm = domain.casefold().removeprefix("www.")
    if host != domain_norm and not domain_norm.endswith("." + host):
        # Different host than company domain is fine when found on the page; we only
        # block invented name+domain patterns against the company domain.
        return email.strip()

    name_bits = [
        b
        for b in "".join(ch if ch.isalnum() else " " for ch in name.casefold()).split()
        if b
    ]
    if len(name_bits) >= 2:
        guesses = {
            f"{name_bits[0]}.{name_bits[-1]}@{domain_norm}",
            f"{name_bits[0]}{name_bits[-1]}@{domain_norm}",
            f"{name_bits[0][0]}{name_bits[-1]}@{domain_norm}",
            f"{name_bits[0]}_{name_bits[-1]}@{domain_norm}",
        }
        if cleaned in guesses:
            return None
    return email.strip()
