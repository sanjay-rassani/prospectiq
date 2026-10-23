"""Discover page, poll-all feeds, and SSE progress stream."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdapterKind, SourceFeed
from app.services.discovery.rss import add_feed, poll_all_feeds


def test_discover_page_ok(client: object) -> None:
    r = client.get("/companies/discover")  # type: ignore[attr-defined]
    assert r.status_code == 200
    assert b"Discover" in r.content
    assert b"activity-log" in r.content
    assert b"EventSource" in r.content
    assert b"stepper" in r.content
    assert b"Live activity" in r.content
    assert b"Focus preset" in r.content
    assert b"Include topics" in r.content
    assert b"Suggested free feed" in r.content
    assert b"TechCrunch" in r.content
    assert b"Free only" in r.content or b"free only" in r.content.lower()
    assert b"data-goto" in r.content


def test_poll_all_feeds_empty(session: Session) -> None:
    stats = poll_all_feeds(session)
    assert stats["feeds"] == 0
    assert stats["new_entries"] == 0
    assert stats["seeded"] == 0
    assert stats["errors"] == 0


def test_poll_all_feeds_with_disabled(session: Session, monkeypatch: object) -> None:
    add_feed(
        session,
        name="Off",
        url="https://feeds.example/off.xml",
        kind=AdapterKind.RSS.value,
        enabled=False,
    )
    add_feed(
        session,
        name="On",
        url="https://feeds.example/on.xml",
        kind=AdapterKind.RSS.value,
        enabled=True,
    )

    import app.services.discovery.rss as rss_mod

    calls: list[str] = []

    def fake_poll(session: Session, feed: SourceFeed, **kwargs: object) -> dict[str, int]:
        calls.append(feed.url)
        on_progress = kwargs.get("on_progress")
        if callable(on_progress):
            on_progress("info", f"fake {feed.name}")
        return {"new_entries": 2, "seeded": 1}

    monkeypatch.setattr(rss_mod, "poll_feed", fake_poll)
    events: list[tuple[str, str]] = []
    stats = poll_all_feeds(
        session,
        seed_new_links=True,
        on_progress=lambda level, msg: events.append((level, msg)),
    )
    assert stats["feeds"] == 1
    assert stats["new_entries"] == 2
    assert stats["seeded"] == 1
    assert calls == ["https://feeds.example/on.xml"]
    assert any("Starting poll" in m for _, m in events)
    assert any("fake On" in m for _, m in events)


def test_discover_poll_stream_sse(client: object, monkeypatch: object) -> None:
    import app.api.companies as companies_api

    def fake_poll(session: object, **kwargs: object) -> dict[str, int]:
        on_progress = kwargs.get("on_progress")
        if callable(on_progress):
            on_progress("info", "Fetching demo…")
            on_progress("ok", "Seeded Demo Co (demo.example)")
        return {
            "feeds": 1,
            "new_entries": 1,
            "seeded": 1,
            "filtered": 0,
            "errors": 0,
        }

    monkeypatch.setattr(companies_api, "poll_all_feeds", fake_poll)
    with client.stream("GET", "/companies/discover/poll/stream") as response:  # type: ignore[attr-defined]
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        body = "".join(response.iter_text())
    assert "Fetching demo" in body
    assert "Seeded Demo Co" in body
    assert "Done" in body
    assert "data:" in body


def test_discover_add_feed_redirect(client: object, session: Session) -> None:
    r = client.post(  # type: ignore[attr-defined]
        "/companies/discover/feeds",
        data={
            "name": "Demo",
            "url": "https://feeds.example/demo2.xml",
            "kind": "rss",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert session.scalar(
        select(SourceFeed).where(SourceFeed.url == "https://feeds.example/demo2.xml")
    )
