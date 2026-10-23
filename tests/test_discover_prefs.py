"""Discover filters and polling prefs."""

from __future__ import annotations

from app.services.discovery.prefs import entry_matches_filters
from app.services.scoring.profile import DiscoverPrefs, OperatorProfile


def test_entry_matches_keywords() -> None:
    profile = OperatorProfile(target_industries=["logistics"])
    prefs = DiscoverPrefs(
        keywords=["warehouse"],
        use_profile_industries_as_keywords=False,
        skip_social_hosts=True,
    )
    ok, _ = entry_matches_filters(
        title="New warehouse automation",
        summary="",
        link="https://acme.example/news",
        prefs=prefs,
        profile=profile,
    )
    assert ok is True

    ok2, reason = entry_matches_filters(
        title="Office party",
        summary="",
        link="https://acme.example/news",
        prefs=prefs,
        profile=profile,
    )
    assert ok2 is False
    assert "keyword" in reason


def test_skip_social_and_exclude() -> None:
    profile = OperatorProfile()
    prefs = DiscoverPrefs(keywords=[], use_profile_industries_as_keywords=False)
    ok, reason = entry_matches_filters(
        title="Hire me",
        summary="",
        link="https://www.linkedin.com/in/someone",
        prefs=prefs,
        profile=profile,
    )
    assert ok is False
    assert "social" in reason

    prefs2 = DiscoverPrefs(
        keywords=[],
        exclude_keywords=["hiring"],
        use_profile_industries_as_keywords=False,
        skip_social_hosts=False,
    )
    ok3, reason3 = entry_matches_filters(
        title="We are hiring engineers",
        summary="",
        link="https://acme.example/jobs",
        prefs=prefs2,
        profile=profile,
    )
    assert ok3 is False
    assert "excluded" in reason3


def test_profile_industries_as_keywords() -> None:
    profile = OperatorProfile(target_industries=["fintech"])
    prefs = DiscoverPrefs(keywords=[], use_profile_industries_as_keywords=True)
    ok, _ = entry_matches_filters(
        title="Fintech payments launch",
        summary="",
        link="https://pay.example/",
        prefs=prefs,
        profile=profile,
    )
    assert ok is True
