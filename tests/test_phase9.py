"""Phase 9: feeds, adapters, feedback, domain policies."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AdapterKind,
    Company,
    FeedEntry,
    OperatorFeedback,
    SourceFeed,
)
from app.services.discovery.feedback import record_feedback
from app.services.discovery.playwright_fallback import (
    fetch_with_playwright,
    set_domain_policy,
)
from app.services.discovery.registry import get_adapter, list_adapters
from app.services.discovery.rss import add_feed, poll_feed


def test_adapter_registry() -> None:
    adapters = list_adapters()
    kinds = {a.kind for a in adapters}
    assert AdapterKind.RSS.value in kinds
    assert AdapterKind.GITHUB_RELEASES.value in kinds
    assert get_adapter("rss") is not None


def test_add_and_poll_rss_feed(session: Session, monkeypatch: object) -> None:
    feed = add_feed(
        session,
        name="Demo",
        url="https://feeds.example/demo.xml",
        kind=AdapterKind.RSS.value,
    )
    assert feed.id is not None

    sample = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Demo</title>
    <item>
      <title>Acme launches</title>
      <link>https://acme-rss.example/news/1</link>
      <guid>https://acme-rss.example/news/1</guid>
      <description>Acme Logistics opened a third depot.</description>
    </item>
    <item>
      <title>Acme launches</title>
      <link>https://acme-rss.example/news/1</link>
      <guid>https://acme-rss.example/news/1</guid>
    </item>
    </channel></rss>"""

    class FakeResp:
        text = sample

        def raise_for_status(self) -> None:
            return None

    class FakeFetcher:
        def __init__(self) -> None:
            self.client = type("C", (), {"get": lambda self, url, headers=None: FakeResp()})()
            self.rate_limiter = type(
                "R",
                (),
                {"acquire": lambda self, d: None, "release": lambda self: None},
            )()

        def close(self) -> None:
            return None

    # Do not seed (would hit network); patch seed_targets.
    import app.services.discovery.rss as rss_mod

    monkeypatch.setattr(rss_mod, "seed_targets", lambda *a, **k: [])  # type: ignore[arg-type]
    stats = poll_feed(session, feed, fetcher=FakeFetcher(), seed_new_links=True)  # type: ignore[arg-type]
    assert stats["new_entries"] == 1  # second item deduped
    entries = session.scalars(select(FeedEntry).where(FeedEntry.feed_id == feed.id)).all()
    assert len(entries) == 1

    # Second poll adds nothing.
    stats2 = poll_feed(session, feed, fetcher=FakeFetcher(), seed_new_links=False)  # type: ignore[arg-type]
    assert stats2["new_entries"] == 0


def test_feedback_suggests_threshold_nudge(session: Session) -> None:
    company = Company(name="FB Co", domain="fb.example", status="researched")
    session.add(company)
    session.flush()
    row = record_feedback(session, company, verdict="bad", reason="wrong industry")
    assert row.suggested_adjustment
    text = row.suggested_adjustment.casefold()
    assert "threshold" in text or "industr" in text
    assert session.scalar(select(OperatorFeedback).where(OperatorFeedback.company_id == company.id))


def test_playwright_policy_and_missing_dep(session: Session) -> None:
    policy = set_domain_policy(
        session, "https://spa.example.com", playwright_fallback=True, notes="JS app"
    )
    assert policy.domain == "spa.example.com"
    assert policy.playwright_fallback is True
    result = fetch_with_playwright("https://spa.example.com/")
    # Either playwright missing (ok=False with install hint) or installed.
    assert "ok" in result


def test_settings_page(client: object) -> None:
    response = client.get("/settings")  # type: ignore[attr-defined]
    assert response.status_code == 200
    assert b"Adapters" in response.content
    assert b"Feeds" in response.content


def test_add_feed_via_ui(client: object, session: Session) -> None:
    response = client.post(  # type: ignore[attr-defined]
        "/settings/feeds",
        data={
            "name": "UI Feed",
            "url": "https://ui-feed.example/atom.xml",
            "kind": "rss",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    feed = session.scalar(select(SourceFeed).where(SourceFeed.url.endswith("atom.xml")))
    assert feed is not None
    assert feed.name == "UI Feed"
