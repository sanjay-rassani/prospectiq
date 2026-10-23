"""Discover filter helpers (feeds only — no Google/LinkedIn credential research)."""

from __future__ import annotations

from urllib.parse import urlparse

from app.services.scoring.profile import DiscoverPrefs, OperatorProfile

# Hosts we never treat as company websites for auto-seed.
SOCIAL_HOST_SUFFIXES = (
    "linkedin.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "fb.com",
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "threads.net",
)


def effective_match_keywords(prefs: DiscoverPrefs, profile: OperatorProfile) -> list[str]:
    keys = [k.strip() for k in prefs.keywords if k.strip()]
    if prefs.use_profile_industries_as_keywords:
        keys.extend(i.strip() for i in profile.target_industries if i.strip())
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        low = k.casefold()
        if low not in seen:
            seen.add(low)
            out.append(k)
    return out


def host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_social_host(url: str) -> bool:
    host = host_of(url)
    return any(host == s or host.endswith("." + s) for s in SOCIAL_HOST_SUFFIXES)


def entry_matches_filters(
    *,
    title: str,
    summary: str,
    link: str,
    prefs: DiscoverPrefs,
    profile: OperatorProfile,
) -> tuple[bool, str]:
    """Return (ok, reason_if_skipped)."""
    blob = f"{title}\n{summary}\n{link}".casefold()

    for bad in prefs.exclude_keywords:
        if bad.strip() and bad.strip().casefold() in blob:
            return False, f"excluded keyword “{bad.strip()}”"

    if prefs.skip_social_hosts and is_social_host(link):
        return False, "social/profile host (not a company site)"

    must = effective_match_keywords(prefs, profile)
    if must and not any(k.casefold() in blob for k in must):
        return False, "no keyword/industry match"

    return True, ""
