"""Filter-driven lead discovery: queries, scoring, adapters, engine, UI."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.models.lead import DiscoveryLead, IntentClass, LeadKind, LeadStatus
from app.services.contacts.ssrf import UnsafeUrlError, assert_public_http_url
from app.services.leads.adapters.base import RawCandidate
from app.services.leads.adapters.hackernews import HackerNewsAdapter
from app.services.leads.engine import run_lead_discovery
from app.services.leads.filters import TargetingFilters, build_search_queries
from app.services.leads.persist import persist_candidate
from app.services.leads.scoring import score_candidate


def _filters(**kwargs: object) -> TargetingFilters:
    data: dict = dict(
        lead_types=["project_request", "company_seeking_dev"],
        services=["automation", "backend_api"],
        industries=["logistics"],
        industry_mode="flexible",
        geographies=["UK"],
        include_remote=True,
        optional_keywords=["automation"],
        exclude_keywords=["hiring"],
        min_relevance=20,
        enabled_sources=["hackernews"],
        prefer_high_intent=True,
        seed_new_links=False,
        max_per_source=10,
    )
    data.update(kwargs)
    return TargetingFilters(**data)  # type: ignore[arg-type]


def test_build_search_queries_include_intent() -> None:
    queries = build_search_queries(_filters())
    assert queries
    blob = " ".join(q.text.casefold() for q in queries)
    assert "looking for" in blob or "need" in blob or "rfp" in blob


def test_score_high_intent_vs_company() -> None:
    high = score_candidate(
        title="Looking for a developer to automate warehouse ops",
        description="Need a custom API and workflow automation in the UK.",
        url="https://news.ycombinator.com/item?id=1",
        source_category="p1_intent",
        filters=_filters(),
    )
    assert high.intent_class == IntentClass.HIGH_INTENT.value
    assert high.lead_kind == LeadKind.PROJECT.value
    assert high.relevance >= 40
    assert high.intent_indicators

    company = score_candidate(
        title="Acme Logistics launches a new depot",
        description="Freight company expansion in logistics.",
        url="https://acme-logistics.example/news",
        source_category="p2_business",
        filters=_filters(),
    )
    assert company.intent_class in {
        IntentClass.POTENTIAL.value,
        IntentClass.EMERGING.value,
    }
    assert high.relevance > company.relevance


def test_score_exclude_and_strict_industry() -> None:
    skipped = score_candidate(
        title="We're hiring a developer",
        description="Careers page",
        url="https://jobs.example/hiring",
        source_category="p2_business",
        filters=_filters(),
    )
    assert skipped.intent_class == IntentClass.LOW_RELEVANCE.value
    assert skipped.relevance == 0

    strict = score_candidate(
        title="Looking for a developer to build an API",
        description="SaaS billing automation",
        url="https://example.com/rfp",
        source_category="p1_intent",
        filters=_filters(industry_mode="strict", industries=["healthcare"]),
    )
    assert strict.intent_class == IntentClass.LOW_RELEVANCE.value


def test_persist_dedupes_and_keeps_rejection(session: Session) -> None:
    filters = _filters()
    raw = RawCandidate(
        source_kind="hackernews",
        source_name="Hacker News",
        source_category="p1_intent",
        listing_id="hn:42",
        url="https://example.com/looking-for-developer",
        title="Looking for a developer to automate ops",
        description="Need workflow automation for logistics in the UK.",
    )
    first, action = persist_candidate(session, raw, filters)
    assert action == "created"
    assert first is not None
    first.status = LeadStatus.REJECTED.value
    session.flush()

    raw2 = RawCandidate(
        source_kind="hackernews",
        source_name="Hacker News",
        source_category="p1_intent",
        listing_id="hn:42",
        url="https://example.com/looking-for-developer",
        title="Looking for a developer to automate ops (updated)",
        description="Need workflow automation for logistics in the UK.",
    )
    again, action2 = persist_candidate(session, raw2, filters)
    assert action2 == "rejected_kept"
    assert again is not None
    assert again.id == first.id
    assert again.status == LeadStatus.REJECTED.value

    from sqlalchemy import select

    rows = list(session.scalars(select(DiscoveryLead)).all())
    assert len(rows) == 1


def test_persist_skips_ssrf(session: Session) -> None:
    filters = _filters(min_relevance=0)
    raw = RawCandidate(
        source_kind="hackernews",
        source_name="Hacker News",
        source_category="p1_intent",
        listing_id="hn:loop",
        url="http://127.0.0.1/team",
        title="Looking for a developer",
        description="Need automation",
    )
    lead, action = persist_candidate(session, raw, filters)
    assert lead is None
    assert action == "skipped_unsafe_url"


def test_hackernews_adapter_mocked() -> None:
    adapter = HackerNewsAdapter()
    fetcher = MagicMock()
    fetcher.rate_limiter = MagicMock()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "hits": [
            {
                "objectID": "99",
                "title": "Ask HN: looking for a developer to automate invoicing",
                "url": "https://example.com/project",
                "story_text": "Need API automation",
                "created_at": datetime.now(UTC).isoformat(),
            }
        ]
    }
    fetcher.client.get.return_value = response
    settings = MagicMock()
    found = adapter.search(
        session=MagicMock(),
        filters=_filters(),
        fetcher=fetcher,
        settings=settings,
        on_progress=None,
        limit=10,
    )
    assert len(found) == 1
    assert found[0].source_kind == "hackernews"
    assert "99" in found[0].listing_id


def test_engine_partial_source_failure(session: Session, monkeypatch: object) -> None:
    from app.services.leads import engine as engine_mod

    class Boom:
        key = "hackernews"

        def capability(self, settings: object) -> object:
            from app.services.leads.adapters.base import AdapterCapability

            return AdapterCapability(
                key="hackernews",
                label="HN",
                category="p1_intent",
                description="x",
                availability="available",
                limitations="",
                enabled_by_default=True,
            )

        def search(self, **kwargs: object) -> list:
            raise RuntimeError("network down")

    class EmptyRss:
        key = "rss_feeds"

        def capability(self, settings: object) -> object:
            from app.services.leads.adapters.base import AdapterCapability

            return AdapterCapability(
                key="rss_feeds",
                label="RSS",
                category="p4_other",
                description="x",
                availability="available",
                limitations="",
                enabled_by_default=True,
            )

        def search(self, **kwargs: object) -> list:
            return []

    monkeypatch.setattr(
        engine_mod,
        "adapters_by_key",
        lambda: {"hackernews": Boom(), "rss_feeds": EmptyRss()},
    )
    monkeypatch.setattr(
        engine_mod,
        "list_capabilities",
        lambda settings=None: [
            Boom().capability(None),
            EmptyRss().capability(None),
        ],
    )
    stats = run_lead_discovery(
        session,
        _filters(enabled_sources=["hackernews", "rss_feeds"]),
        fetcher=MagicMock(close=MagicMock()),
    )
    assert stats.sources_failed == 1
    assert stats.sources_run == 1
    assert stats.errors


def test_discover_prefs_ajax_save_applies_sources(
    client: object, monkeypatch: object, tmp_path: object
) -> None:
    from pathlib import Path

    from app.services.scoring import profile as profile_mod

    path = Path(str(tmp_path)) / "operator_profile.yaml"
    path.write_text("positioning: test\ndiscovery: {}\n")
    monkeypatch.setattr(profile_mod, "DEFAULT_PROFILE_PATH", path)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "app.api.companies.DEFAULT_PROFILE_PATH", path
    )

    r = client.post(  # type: ignore[attr-defined]
        "/companies/discover/prefs?ajax=1",
        data={
            "focus_preset": "custom",
            "source_choice": ["hackernews", "contracts_uk", "github_issues"],
            "engine_choice": ["duckduckgo"],
            "lead_type": ["project_request"],
            "service_choice": ["automation"],
            "industry_choice": ["saas"],
            "industry_mode": "flexible",
            "location_choice": ["United Kingdom", "remote"],
            "include_remote": "on",
            "required_keywords": "automation",
            "min_relevance": "30",
            "prefer_high_intent": "on",
            "max_new_entries_per_feed": "25",
            "max_seeds_per_poll": "15",
        },
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "hackernews" in body["enabled_sources"]
    assert "contracts_uk" in body["enabled_sources"]
    assert "github_issues" in body["enabled_sources"]
    assert "United Kingdom" in body["geographies"]
    assert body["required_keywords"] == ["automation"]

    from app.services.scoring.profile import reload_operator_profile
    from app.services.leads.filters import filters_from_prefs

    profile = reload_operator_profile()
    filters = filters_from_prefs(profile.discovery, profile)
    assert "hackernews" in filters.enabled_sources
    assert "github_issues" in filters.enabled_sources
    assert filters.required_keywords == ["automation"]
    assert "United Kingdom" in filters.geographies


def test_discover_sources_ui_no_marketplaces(client: object) -> None:
    r = client.get("/companies/discover")  # type: ignore[attr-defined]
    assert r.status_code == 200
    body = r.text
    assert "Services" in body
    assert "Locations" in body
    assert "Hacker News" in body
    assert "UK Contracts Finder" in body
    assert "Your custom sources" in body
    assert "Search engines" in body
    assert "Active (hide rejected)" in body
    assert "Rejected only" in body
    assert 'value="upwork"' not in body
    assert 'value="fiverr"' not in body
    assert 'value="linkedin"' not in body
    assert "not scraped" in body.casefold()


def test_discover_hides_rejected_by_default(session: Session, client: object) -> None:
    active = DiscoveryLead(
        source_kind="hackernews",
        source_name="Hacker News",
        source_category="p1_intent",
        listing_id="hn:active-1",
        canonical_url="https://example.com/active",
        title="Active lead keep me",
        description="Need automation",
        lead_kind=LeadKind.PROJECT.value,
        intent_class=IntentClass.HIGH_INTENT.value,
        relevance_score=80,
        status=LeadStatus.NEW.value,
        discovered_at=datetime.now(UTC),
    )
    rejected = DiscoveryLead(
        source_kind="hackernews",
        source_name="Hacker News",
        source_category="p1_intent",
        listing_id="hn:rejected-1",
        canonical_url="https://example.com/rejected",
        title="Rejected lead hide me",
        description="Need automation",
        lead_kind=LeadKind.PROJECT.value,
        intent_class=IntentClass.HIGH_INTENT.value,
        relevance_score=90,
        status=LeadStatus.REJECTED.value,
        discovered_at=datetime.now(UTC),
    )
    session.add_all([active, rejected])
    session.flush()

    default_page = client.get("/companies/discover")  # type: ignore[attr-defined]
    assert default_page.status_code == 200
    assert "Active lead keep me" in default_page.text
    assert "Rejected lead hide me" not in default_page.text

    rejected_page = client.get(  # type: ignore[attr-defined]
        "/companies/discover?lead_status=rejected"
    )
    assert rejected_page.status_code == 200
    assert "Rejected lead hide me" in rejected_page.text
    assert "Active lead keep me" not in rejected_page.text


def test_lead_qualify_reject(session: Session, client: object) -> None:
    lead = DiscoveryLead(
        source_kind="hackernews",
        source_name="Hacker News",
        source_category="p1_intent",
        listing_id="hn:test-1",
        canonical_url="https://example.com/need-dev",
        title="Looking for a developer",
        description="Need automation",
        lead_kind=LeadKind.PROJECT.value,
        intent_class=IntentClass.HIGH_INTENT.value,
        relevance_score=80,
        discovered_at=datetime.now(UTC),
    )
    session.add(lead)
    session.flush()
    r = client.post(  # type: ignore[attr-defined]
        f"/leads/{lead.id}/qualify", follow_redirects=False
    )
    assert r.status_code == 303
    session.refresh(lead)
    assert lead.status == LeadStatus.QUALIFIED.value
    r2 = client.post(  # type: ignore[attr-defined]
        f"/leads/{lead.id}/reject", follow_redirects=False
    )
    assert r2.status_code == 303
    session.refresh(lead)
    assert lead.status == LeadStatus.REJECTED.value


def test_leads_bulk_qualify_and_reject(session: Session, client: object) -> None:
    leads = []
    for i in range(3):
        lead = DiscoveryLead(
            source_kind="hackernews",
            source_name="Hacker News",
            source_category="p1_intent",
            listing_id=f"hn:bulk-{i}",
            canonical_url=f"https://example.com/bulk-{i}",
            title=f"Bulk lead {i}",
            description="Need automation",
            lead_kind=LeadKind.PROJECT.value,
            intent_class=IntentClass.HIGH_INTENT.value,
            relevance_score=70,
            discovered_at=datetime.now(UTC),
        )
        session.add(lead)
        leads.append(lead)
    session.flush()

    r = client.post(  # type: ignore[attr-defined]
        "/leads/bulk",
        data={
            "action": "qualify",
            "lead_id": [str(leads[0].id), str(leads[1].id)],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    from urllib.parse import unquote

    assert "Bulk OK: 2 lead(s)" in unquote(r.headers.get("location") or "")
    session.refresh(leads[0])
    session.refresh(leads[1])
    session.refresh(leads[2])
    assert leads[0].status == LeadStatus.QUALIFIED.value
    assert leads[1].status == LeadStatus.QUALIFIED.value
    assert leads[2].status == LeadStatus.NEW.value

    r2 = client.post(  # type: ignore[attr-defined]
        "/leads/bulk",
        data={
            "action": "reject",
            "lead_id": [str(leads[0].id), str(leads[1].id), str(leads[2].id)],
        },
        follow_redirects=False,
    )
    assert r2.status_code == 303
    for lead in leads:
        session.refresh(lead)
        assert lead.status == LeadStatus.REJECTED.value

    page = client.get("/companies/discover?lead_status=rejected")  # type: ignore[attr-defined]
    assert page.status_code == 200
    assert "Bulk lead 0" in page.text
    active = client.get("/companies/discover")  # type: ignore[attr-defined]
    assert active.status_code == 200
    assert "Bulk lead 0" not in active.text
    assert 'id="leads-bulk-form"' in page.text or "rejected" in page.text.casefold()


def test_public_http_still_blocks_loopback() -> None:
    try:
        assert_public_http_url("http://127.0.0.1/x")
        raise AssertionError("expected UnsafeUrlError")
    except UnsafeUrlError:
        pass
