"""RSS/Atom polling with feedparser; dedupe by entry id/link (P9-1)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import mktime
from typing import Any
from urllib.parse import urlparse

import feedparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdapterKind, FeedEntry, SourceFeed, SourceType
from app.services.discovery.seed import seed_targets
from app.services.fetcher import Fetcher

logger = logging.getLogger(__name__)


def _entry_uid(entry: dict[str, Any]) -> str:
    for key in ("id", "guid", "link"):
        value = entry.get(key)
        if value:
            return str(value)[:1024]
    title = entry.get("title") or ""
    published = entry.get("published") or entry.get("updated") or ""
    return f"{title}|{published}"[:1024]


def _entry_published(entry: dict[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime.fromtimestamp(mktime(parsed), tz=UTC)
            except (OverflowError, ValueError, TypeError):
                pass
    for key in ("published", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except (TypeError, ValueError, IndexError):
            continue
    return None


def poll_feed(
    session: Session,
    feed: SourceFeed,
    *,
    fetcher: Fetcher | None = None,
    seed_new_links: bool = True,
) -> dict[str, int]:
    """Fetch a feed, persist new entries, optionally seed companies from links."""
    if not feed.enabled:
        return {"skipped": 1}

    owns = fetcher is None
    fetcher = fetcher or Fetcher()
    new_entries = 0
    seeded = 0
    try:
        # Use httpx via fetcher client for politeness — read raw body for feedparser.
        domain = urlparse(feed.url).hostname or "feed"
        fetcher.rate_limiter.acquire(domain)
        try:
            response = fetcher.client.get(
                feed.url,
                headers={
                    "Accept": (
                        "application/rss+xml, application/atom+xml, "
                        "application/xml, text/xml"
                    )
                },
            )
            response.raise_for_status()
            raw = response.text
        finally:
            fetcher.rate_limiter.release()

        parsed = feedparser.parse(raw)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise ValueError(f"feed parse error: {getattr(parsed, 'bozo_exception', 'unknown')}")

        for entry in parsed.entries:
            link = (entry.get("link") or "").strip()
            if not link:
                continue
            uid = _entry_uid(entry)
            existing = session.scalar(
                select(FeedEntry).where(
                    FeedEntry.feed_id == feed.id,
                    FeedEntry.entry_id == uid,
                )
            )
            if existing is not None:
                continue

            row = FeedEntry(
                feed_id=feed.id,
                entry_id=uid,
                link=link[:2048],
                title=(entry.get("title") or None),
                published_at=_entry_published(entry),
                summary=(entry.get("summary") or entry.get("description") or None),
                processed=False,
            )
            session.add(row)
            session.flush()
            new_entries += 1

            if seed_new_links and feed.kind in {
                AdapterKind.RSS.value,
                AdapterKind.GITHUB_RELEASES.value,
                AdapterKind.CHANGELOG.value,
            }:
                try:
                    outcomes = seed_targets(
                        session,
                        link,
                        fetcher=fetcher,
                    )
                    if outcomes:
                        row.company_id = outcomes[0].company.id
                        row.processed = True
                        seeded += 1
                        # Tag latest snapshot source type when present.
                        company = outcomes[0].company
                        if outcomes[0].snapshot is not None:
                            outcomes[0].snapshot.source_type = (
                                SourceType.RSS.value
                                if feed.kind == AdapterKind.RSS.value
                                else SourceType.TECHNICAL.value
                            )
                            _ = company
                except ValueError as exc:
                    logger.info("feed entry %s not seedable: %s", link, exc)

        feed.last_fetched_at = datetime.now(UTC)
        feed.last_error = None
        session.flush()
        return {"new_entries": new_entries, "seeded": seeded}
    except Exception as exc:
        feed.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        session.flush()
        logger.warning("poll_feed %s failed: %s", feed.url, exc)
        raise
    finally:
        if owns:
            fetcher.close()


def add_feed(
    session: Session,
    *,
    name: str,
    url: str,
    kind: str = AdapterKind.RSS.value,
    enabled: bool = True,
    rate_limit_seconds: float = 5.0,
) -> SourceFeed:
    existing = session.scalar(select(SourceFeed).where(SourceFeed.url == url.strip()))
    if existing is not None:
        existing.name = name.strip() or existing.name
        existing.enabled = enabled
        existing.kind = kind
        existing.rate_limit_seconds = rate_limit_seconds
        session.flush()
        return existing
    feed = SourceFeed(
        name=name.strip() or url.strip(),
        url=url.strip(),
        kind=kind,
        enabled=enabled,
        rate_limit_seconds=rate_limit_seconds,
    )
    session.add(feed)
    session.flush()
    return feed
