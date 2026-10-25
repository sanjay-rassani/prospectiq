"""SearXNG search + public page research (no Google HTML scrape)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.config import Settings
from app.services.fetcher import ExtractedContent, FetchResult
from app.services.leads.adapters.searxng import SearxngAdapter, _should_visit
from app.services.leads.filters import TargetingFilters


def test_should_visit_skips_serp_and_linkedin() -> None:
    assert _should_visit("https://example.com/need-dev") is True
    assert _should_visit("https://www.google.com/search?q=x") is False
    assert _should_visit("https://duckduckgo.com/?q=x") is False
    assert _should_visit("https://www.linkedin.com/in/someone") is False
    assert _should_visit("http://127.0.0.1/secret") is False
    assert _should_visit("https://github.com/foo/backend-template") is False
    assert _should_visit("https://www.upwork.com/hire/developers") is False


def test_score_rejects_github_repos() -> None:
    from app.services.leads.filters import TargetingFilters
    from app.services.leads.scoring import score_candidate

    scored = score_candidate(
        title="usman5K/backend-fastapi-template",
        description="A scalable FastAPI backend template for developers",
        url="https://github.com/usman5K/backend-fastapi-template",
        source_category="p2_business",
        filters=TargetingFilters(seed_new_links=False),
    )
    assert scored.relevance == 0
    assert "repo" in scored.reasons[0].casefold() or "not a buying" in scored.reasons[0].casefold()


def test_score_rejects_stale_leads() -> None:
    from datetime import UTC, datetime, timedelta

    from app.services.leads.filters import TargetingFilters, searx_time_range
    from app.services.leads.scoring import score_candidate

    assert searx_time_range(7) == "week"
    assert searx_time_range(30) == "month"
    assert searx_time_range(0) is None

    old = score_candidate(
        title="Looking for a developer to automate CRM",
        description="Need a custom API and workflow automation.",
        url="https://example.com/old-rfp",
        source_category="p1_intent",
        filters=TargetingFilters(seed_new_links=False, max_age_days=90),
        published_at=datetime.now(UTC) - timedelta(days=400),
    )
    assert old.relevance == 0
    assert "too old" in old.reasons[0].casefold()

    fresh = score_candidate(
        title="Looking for a developer to automate CRM",
        description="Need a custom API and workflow automation.",
        url="https://example.com/new-rfp",
        source_category="p1_intent",
        filters=TargetingFilters(seed_new_links=False, max_age_days=90),
        published_at=datetime.now(UTC) - timedelta(days=3),
    )
    assert fresh.relevance >= 40
    assert any("fresh" in r.casefold() for r in fresh.reasons)


def test_searxng_visits_public_pages(monkeypatch: object) -> None:
    adapter = SearxngAdapter()
    settings = Settings(searxng_url="http://127.0.0.1:8080")
    filters = TargetingFilters(
        enabled_sources=["searxng"],
        search_engines=["duckduckgo"],
        services=["automation"],
        lead_types=["project_request"],
        max_per_source=5,
        seed_new_links=False,
    )

    def fake_hits(**kwargs: object) -> list[dict[str, str]]:
        return [
            {
                "url": "https://example.com/looking-for-developer",
                "title": "Looking for a developer",
                "snippet": "Need automation",
                "query": "need automation",
            }
        ]

    monkeypatch.setattr(adapter, "_search_hits", fake_hits)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "app.services.leads.adapters.searxng._should_visit",
        lambda url, title="": True,
    )

    extracted = ExtractedContent(
        text="We need a developer to automate CRM workflows for our SaaS.",
        title="Looking for a developer",
        published_at=None,
        content_hash="abc",
    )
    fetch_result = FetchResult(
        ok=True,
        url="https://example.com/looking-for-developer",
        final_url="https://example.com/looking-for-developer",
        http_status=200,
        extracted=extracted,
    )
    fetcher = MagicMock()
    fetcher.fetch.return_value = fetch_result

    logs: list[tuple[str, str]] = []
    found = adapter.search(
        session=SimpleNamespace(),
        filters=filters,
        fetcher=fetcher,
        settings=settings,
        on_progress=lambda level, msg: logs.append((level, msg)),
        limit=5,
    )
    assert len(found) == 1
    assert found[0].extra.get("researched") is True
    assert "automate CRM" in found[0].description
    assert any("Visiting" in msg for _, msg in logs)
    fetcher.fetch.assert_called_once()


def test_capability_needs_searxng_url() -> None:
    adapter = SearxngAdapter()
    cap = adapter.capability(
        Settings(
            searxng_url="",
            searxng_extra_urls="",
            searxng_use_public_directory=False,
        )
    )
    assert cap.availability == "optional_config"
    cap2 = adapter.capability(Settings(searxng_url="http://127.0.0.1:8080"))
    assert cap2.availability == "available"
    assert "visit" in cap2.description.casefold() or "research" in cap2.description.casefold()
    cap3 = adapter.capability(
        Settings(searxng_url="", searxng_use_public_directory=True)
    )
    assert cap3.availability == "available"


def test_resolve_bases_prefers_local(monkeypatch: object) -> None:
    from app.services.leads import searx_directory as directory

    monkeypatch.setattr(
        directory,
        "fetch_public_instances",
        lambda limit=12, timeout=25.0: [
            directory.PublicInstance(
                url="https://example-public.example",
                success_pct=100.0,
                median_s=0.2,
            )
        ],
    )
    monkeypatch.setattr(
        directory,
        "is_safe_public_http_url",
        lambda url: "example-public.example" in url or "127.0.0.1" in url,
    )
    bases = directory.resolve_searx_bases(
        primary_url="http://127.0.0.1:8080",
        extra_urls=["https://example-public.example"],
        use_public_directory=True,
        public_limit=2,
    )
    assert bases[0] == "http://127.0.0.1:8080"
    assert "https://example-public.example" in bases
