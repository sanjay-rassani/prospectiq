"""Hacker News via the public Algolia API (documented, no key)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import Settings
from app.services.fetcher import Fetcher
from app.services.leads.adapters.base import (
    AdapterCapability,
    RawCandidate,
    emit,
)
from app.services.leads.filters import TargetingFilters, build_search_queries

# Newest-first; better for live buying requests than relevance-only search.
HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"


class HackerNewsAdapter:
    key = "hackernews"

    def capability(self, settings: Settings) -> AdapterCapability:
        return AdapterCapability(
            key=self.key,
            label="Hacker News (Algolia)",
            category="p1_intent",
            description=(
                "Public HN search API. Finds Ask HN / stories where people request "
                "builders, automation, or software work."
            ),
            availability="available",
            limitations="Community posts, not verified budgets. No private data.",
            priority=10,
            enabled_by_default=True,
        )

    def search(
        self,
        *,
        session: object,
        filters: TargetingFilters,
        fetcher: Fetcher,
        settings: Settings,
        on_progress: object,
        limit: int,
    ) -> list[RawCandidate]:
        queries = [
            q
            for q in build_search_queries(filters)
            if q.intent in {"high_intent", "education", "general"}
        ][:3]
        if not queries:
            queries = build_search_queries(filters)[:2]
        found: list[RawCandidate] = []
        seen: set[str] = set()
        max_age = int(getattr(filters, "max_age_days", 0) or 0)
        cutoff_i: int | None = None
        if max_age > 0:
            cutoff_i = int((datetime.now(UTC) - timedelta(days=max_age)).timestamp())

        for query in queries:
            age_note = f" · last {max_age}d" if max_age > 0 else ""
            emit(on_progress, "info", f'HN search: “{query.text}”{age_note}')  # type: ignore[arg-type]
            params: dict[str, str] = {
                "query": query.text,
                "tags": "story",
                "hitsPerPage": str(min(limit, 20)),
            }
            if cutoff_i is not None:
                params["numericFilters"] = f"created_at_i>{cutoff_i}"
            try:
                fetcher.rate_limiter.acquire("hn.algolia.com")
                try:
                    response = fetcher.client.get(HN_SEARCH, params=params)
                    response.raise_for_status()
                    payload = response.json()
                finally:
                    fetcher.rate_limiter.release()
            except Exception as exc:  # noqa: BLE001
                emit(on_progress, "error", f"HN search failed: {exc}")  # type: ignore[arg-type]
                continue
            hits = payload.get("hits") if isinstance(payload, dict) else None
            if not isinstance(hits, list):
                continue
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                cand = _from_hit(hit)
                if cand is None or cand.listing_id in seen:
                    continue
                seen.add(cand.listing_id)
                found.append(cand)
                if len(found) >= limit:
                    return found
        emit(on_progress, "ok", f"HN: {len(found)} candidate(s)")  # type: ignore[arg-type]
        return found


def _from_hit(hit: dict[str, Any]) -> RawCandidate | None:
    object_id = str(hit.get("objectID") or "").strip()
    title = (hit.get("title") or hit.get("story_title") or "").strip()
    url = (hit.get("url") or "").strip()
    if not url and object_id:
        url = f"https://news.ycombinator.com/item?id={object_id}"
    if not title or not url:
        return None
    story_text = (hit.get("story_text") or hit.get("comment_text") or "") or ""
    created = hit.get("created_at")
    published: datetime | None = None
    if isinstance(created, str):
        try:
            published = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
        except ValueError:
            published = None
    listing_id = object_id or url
    excerpt = str(story_text)[:400] or title
    return RawCandidate(
        source_kind="hackernews",
        source_name="Hacker News",
        source_category="p1_intent",
        listing_id=f"hn:{listing_id}"[:512],
        url=url[:2048],
        title=title[:512],
        description=str(story_text)[:4000],
        excerpt=excerpt,
        published_at=published,
        extra={"hn_object_id": object_id, "points": hit.get("points")},
    )
