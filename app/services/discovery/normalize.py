"""Domain and URL normalization.

Dedup correctness (FR-02) lives here: two seed strings that refer to the same company must
collapse to one domain key. The rules are deliberately conservative — we keep meaningful
subdomains (blog.example.com ≠ example.com) but strip www and trailing punctuation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Hostnames that are never a company domain.
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
    }
)


@dataclass(frozen=True, slots=True)
class NormalizedTarget:
    """A seed entry reduced to the fields we need to create or look up a company."""

    domain: str
    url: str
    name_hint: str | None = None


def normalize_domain(value: str) -> str:
    """Return the canonical domain for deduplication.

    Accepts a bare domain, a URL, or a host with a path. Raises ValueError when the input
    cannot be interpreted as a public HTTP(S) host.
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("empty domain")

    # Allow "Name | https://example.com" callers to pass only the domain side.
    if "|" in raw and "://" not in raw.split("|", 1)[0]:
        raw = raw.split("|", 1)[-1].strip()

    candidate = raw
    if "://" not in candidate:
        # Bare domains and host/path forms: give urlparse a scheme so netloc populates.
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError(f"no host in {value!r}")
    if host in _BLOCKED_HOSTS or host.endswith(".local"):
        raise ValueError(f"blocked host: {host}")
    if not re.match(r"^[a-z0-9.-]+$", host) or "." not in host:
        raise ValueError(f"invalid domain: {host}")

    if host.startswith("www."):
        host = host[4:]
    return host


def canonicalize_url(value: str, *, default_path: str = "/") -> str:
    """Build a stable https URL for fetching from a domain or URL string."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("empty url")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    domain = normalize_domain(raw)
    path = parsed.path or default_path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"https://{domain}{path}{query}"


def parse_seed_line(line: str) -> NormalizedTarget:
    """Parse one seed line.

    Accepted forms:
      example.com
      https://example.com/about
      Acme Corp | example.com
      Acme Corp | https://example.com/about
    """
    raw = line.strip()
    if not raw or raw.startswith("#"):
        raise ValueError("empty or comment line")

    name_hint: str | None = None
    target = raw
    if "|" in raw:
        left, right = raw.split("|", 1)
        left, right = left.strip(), right.strip()
        if right:
            name_hint = left or None
            target = right
        else:
            target = left

    domain = normalize_domain(target)
    url = canonicalize_url(target)
    if name_hint is None:
        # Prefer a human-ish placeholder until extraction fills in a real name.
        name_hint = domain.split(".")[0].replace("-", " ").title()
    return NormalizedTarget(domain=domain, url=url, name_hint=name_hint)


def parse_seed_blob(blob: str) -> list[NormalizedTarget]:
    """Parse a multi-line seed textarea into unique targets (first occurrence wins)."""
    seen: set[str] = set()
    out: list[NormalizedTarget] = []
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        target = parse_seed_line(line)
        if target.domain in seen:
            continue
        seen.add(target.domain)
        out.append(target)
    return out
