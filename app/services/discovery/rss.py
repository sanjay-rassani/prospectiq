"""RSS/Atom polling with feedparser; dedupe by entry id/link (P9-1)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import mktime
from typing import Any
from urllib.parse import urlparse

import feedparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdapterKind, Company, FeedEntry, SourceFeed, SourceType
from app.services.discovery.normalize import normalize_domain
from app.services.discovery.prefs import entry_matches_filters
from app.services.discovery.seed import seed_targets
from app.services.fetcher import Fetcher
from app.services.scoring.profile import DiscoverPrefs, get_operator_profile

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, str], None]


def _emit(on_progress: ProgressFn | None, level: str, message: str) -> None:
    if on_progress is not None:
        on_progress(level, message)


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


def _domain_from_link(link: str) -> str | None:
    try:
        return normalize_domain(link)
    except ValueError:
        return None


def poll_feed(
    session: Session,
    feed: SourceFeed,
    *,
    fetcher: Fetcher | None = None,
    seed_new_links: bool | None = None,
    on_progress: ProgressFn | None = None,
    prefs: DiscoverPrefs | None = None,
    seeds_remaining: list[int] | None = None,
) -> dict[str, int]:
    """Fetch a feed, persist new entries, optionally seed companies from links.

    ``seeds_remaining`` is a one-element list used as a mutable counter across feeds
    for ``max_seeds_per_poll``.
    """
    profile = get_operator_profile()
    prefs = prefs or profile.discovery
    do_seed = prefs.seed_new_links if seed_new_links is None else seed_new_links

    if not feed.enabled:
        _emit(on_progress, "info", f'Skipped "{feed.name}" (disabled)')
        return {"skipped": 1}

    owns = fetcher is None
    fetcher = fetcher or Fetcher()
    new_entries = 0
    seeded = 0
    skipped_filter = 0
    try:
        _emit(on_progress, "info", f'Fetching "{feed.name}"…')
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

        total_items = len(parsed.entries)
        _emit(
            on_progress,
            "info",
            f'"{feed.name}": {total_items} item(s) — applying discover filters',
        )

        for entry in parsed.entries:
            if new_entries >= prefs.max_new_entries_per_feed:
                _emit(
                    on_progress,
                    "warn",
                    f'Reached max new entries per feed ({prefs.max_new_entries_per_feed})',
                )
                break

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

            title = (entry.get("title") or "") or ""
            summary = (entry.get("summary") or entry.get("description") or "") or ""
            ok, reason = entry_matches_filters(
                title=title,
                summary=str(summary),
                link=link,
                prefs=prefs,
                profile=profile,
            )
            if not ok:
                skipped_filter += 1
                _emit(on_progress, "info", f"Skip: {reason} — {(title or link)[:80]}")
                # Still record for dedupe so we do not re-check forever.
                session.add(
                    FeedEntry(
                        feed_id=feed.id,
                        entry_id=uid,
                        link=link[:2048],
                        title=(entry.get("title") or None),
                        published_at=_entry_published(entry),
                        summary=str(summary)[:4000] if summary else None,
                        processed=True,
                    )
                )
                session.flush()
                new_entries += 1
                continue

            label = (title or link)[:120]
            row = FeedEntry(
                feed_id=feed.id,
                entry_id=uid,
                link=link[:2048],
                title=(entry.get("title") or None),
                published_at=_entry_published(entry),
                summary=str(summary)[:4000] if summary else None,
                processed=False,
            )
            session.add(row)
            session.flush()
            new_entries += 1
            _emit(on_progress, "info", f"New entry: {label}")

            if not do_seed or feed.kind not in {
                AdapterKind.RSS.value,
                AdapterKind.GITHUB_RELEASES.value,
                AdapterKind.CHANGELOG.value,
            }:
                continue

            if seeds_remaining is not None and seeds_remaining[0] <= 0:
                _emit(on_progress, "warn", "Seed budget for this poll used up")
                continue

            domain_key = _domain_from_link(link)
            if prefs.only_unknown_domains and domain_key:
                known = session.scalar(select(Company.id).where(Company.domain == domain_key))
                if known is not None:
                    _emit(on_progress, "info", f"Already tracking {domain_key} — skip seed")
                    row.company_id = known
                    row.processed = True
                    session.flush()
                    continue

            try:
                _emit(on_progress, "info", f"Seeding {domain_key or link}…")
                outcomes = seed_targets(session, link, fetcher=fetcher)
                if outcomes:
                    row.company_id = outcomes[0].company.id
                    row.processed = True
                    seeded += 1
                    if seeds_remaining is not None:
                        seeds_remaining[0] -= 1
                    company = outcomes[0].company
                    if outcomes[0].snapshot is not None:
                        outcomes[0].snapshot.source_type = (
                            SourceType.RSS.value
                            if feed.kind == AdapterKind.RSS.value
                            else SourceType.TECHNICAL.value
                        )
                    _emit(
                        on_progress,
                        "ok",
                        f"Seeded {company.name} ({company.domain})",
                    )
                else:
                    _emit(on_progress, "info", "Link had no seedable domain")
            except ValueError as exc:
                _emit(on_progress, "warn", f"Could not seed link: {exc}")
                logger.info("feed entry %s not seedable: %s", link, exc)

        feed.last_fetched_at = datetime.now(UTC)
        feed.last_error = None
        session.flush()
        _emit(
            on_progress,
            "ok",
            (
                f'Finished "{feed.name}": {new_entries} new, {seeded} seeded'
                + (f", {skipped_filter} filtered" if skipped_filter else "")
            ),
        )
        return {"new_entries": new_entries, "seeded": seeded, "filtered": skipped_filter}
    except Exception as exc:
        feed.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        session.flush()
        short = str(exc)[:200]
        _emit(on_progress, "error", f'"{feed.name}" failed: {short}')
        logger.warning("poll_feed %s failed: %s", feed.url, exc)
        raise
    finally:
        if owns:
            fetcher.close()


def poll_all_feeds(
    session: Session,
    *,
    fetcher: Fetcher | None = None,
    seed_new_links: bool | None = None,
    on_progress: ProgressFn | None = None,
    prefs: DiscoverPrefs | None = None,
) -> dict[str, int]:
    """Poll every enabled feed. Returns aggregate counts (and error count)."""
    profile = get_operator_profile()
    prefs = prefs or profile.discovery
    feeds = session.scalars(select(SourceFeed).where(SourceFeed.enabled.is_(True))).all()
    owns = fetcher is None
    fetcher = fetcher or Fetcher()
    new_total = 0
    seeded_total = 0
    filtered_total = 0
    errors = 0
    seeds_remaining = [prefs.max_seeds_per_poll]
    try:
        n = len(feeds)
        _emit(on_progress, "info", f"Starting poll — {n} enabled feed(s)")
        do_seed = prefs.seed_new_links if seed_new_links is None else seed_new_links
        _emit(
            on_progress,
            "info",
            (
                f"Behavior: seed={'on' if do_seed else 'off'}"
                f", max_entries/feed={prefs.max_new_entries_per_feed}"
                f", max_seeds/poll={prefs.max_seeds_per_poll}"
                f", skip_social={'on' if prefs.skip_social_hosts else 'off'}"
                f", only_new_domains={'on' if prefs.only_unknown_domains else 'off'}"
            ),
        )
        if n == 0:
            _emit(on_progress, "warn", "No enabled feeds. Add one, then poll again.")
            return {
                "feeds": 0,
                "new_entries": 0,
                "seeded": 0,
                "filtered": 0,
                "errors": 0,
            }

        for idx, feed in enumerate(feeds, start=1):
            _emit(on_progress, "info", f"[{idx}/{n}] {feed.name}")
            try:
                stats = poll_feed(
                    session,
                    feed,
                    fetcher=fetcher,
                    seed_new_links=seed_new_links,
                    on_progress=on_progress,
                    prefs=prefs,
                    seeds_remaining=seeds_remaining,
                )
                new_total += int(stats.get("new_entries", 0))
                seeded_total += int(stats.get("seeded", 0))
                filtered_total += int(stats.get("filtered", 0))
            except Exception:
                errors += 1
                logger.exception("poll feed %s failed", feed.url)
        return {
            "feeds": n,
            "new_entries": new_total,
            "seeded": seeded_total,
            "filtered": filtered_total,
            "errors": errors,
        }
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
