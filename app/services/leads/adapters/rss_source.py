"""Wrap existing RSS/Atom feeds as a supplementary discovery adapter."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import FeedEntry, SourceFeed
from app.services.discovery.rss import poll_all_feeds
from app.services.fetcher import Fetcher
from app.services.leads.adapters.base import (
    AdapterCapability,
    RawCandidate,
    emit,
)
from app.services.leads.filters import TargetingFilters


class RssFeedsAdapter:
    key = "rss_feeds"

    def capability(self, settings: Settings) -> AdapterCapability:
        return AdapterCapability(
            key=self.key,
            label="RSS / Atom / GitHub releases",
            category="p4_other",
            description=(
                "Your configured public feeds. Supplementary to web/project search. "
                "Same pipeline as before."
            ),
            availability="available",
            limitations="Only finds companies linked from feeds you added.",
            priority=40,
            enabled_by_default=True,
        )

    def search(
        self,
        *,
        session: Session,
        filters: TargetingFilters,
        fetcher: Fetcher,
        settings: Settings,
        on_progress: object,
        limit: int,
    ) -> list[RawCandidate]:
        n_feeds = session.scalar(
            select(SourceFeed.id).where(SourceFeed.enabled.is_(True)).limit(1)
        )
        if n_feeds is None:
            emit(on_progress, "warn", "RSS: no enabled feeds configured")  # type: ignore[arg-type]
            return []
        emit(on_progress, "info", "Polling configured RSS/Atom feeds…")  # type: ignore[arg-type]
        poll_all_feeds(
            session,
            fetcher=fetcher,
            seed_new_links=False,
            on_progress=on_progress,  # type: ignore[arg-type]
        )
        rows = list(
            session.scalars(
                select(FeedEntry).order_by(FeedEntry.created_at.desc()).limit(limit * 2)
            ).all()
        )
        found: list[RawCandidate] = []
        for row in rows:
            if not row.link:
                continue
            found.append(
                RawCandidate(
                    source_kind="rss_feeds",
                    source_name="RSS feed",
                    source_category="p2_business",
                    listing_id=f"rss:{row.feed_id}:{row.entry_id}"[:512],
                    url=row.link[:2048],
                    title=(row.title or row.link)[:512],
                    description=(row.summary or "")[:4000],
                    excerpt=(row.summary or row.title or "")[:400],
                    published_at=row.published_at,
                )
            )
            if len(found) >= limit:
                break
        emit(on_progress, "ok", f"RSS: {len(found)} recent matching item(s)")  # type: ignore[arg-type]
        return found
