"""Optional GitHub issue search (public REST API, rate-limited)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.services.fetcher import Fetcher
from app.services.leads.adapters.base import (
    AdapterCapability,
    RawCandidate,
    emit,
)
from app.services.leads.filters import TargetingFilters, build_search_queries

GITHUB_SEARCH = "https://api.github.com/search/issues"


class GitHubIssuesAdapter:
    key = "github_issues"

    def capability(self, settings: Settings) -> AdapterCapability:
        token = bool((settings.github_token or "").strip())
        return AdapterCapability(
            key=self.key,
            label="GitHub public issues",
            category="p1_intent",
            description=(
                "Search public GitHub issues for phrases like “looking for developer”. "
                "Unauthenticated: 10 requests/minute."
            ),
            availability="available",
            requires_config="GITHUB_TOKEN (optional, higher rate limit)" if not token else None,
            limitations="Noisy. Does not search private repos. Off by default.",
            priority=35,
            enabled_by_default=False,
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
        queries = build_search_queries(filters, limit=2)
        qtext = queries[0].text if queries else "looking for developer"
        q = f"{qtext} is:issue is:open"
        max_age = int(getattr(filters, "max_age_days", 0) or 0)
        if max_age > 0:
            since = (datetime.now(UTC) - timedelta(days=max_age)).date().isoformat()
            q = f"{q} created:>{since}"
        emit(on_progress, "info", f"GitHub issues: {q[:100]}")  # type: ignore[arg-type]
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = (settings.github_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            fetcher.rate_limiter.acquire("api.github.com")
            try:
                response = fetcher.client.get(
                    GITHUB_SEARCH,
                    params={"q": q, "per_page": min(limit, 20), "sort": "updated"},
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
            finally:
                fetcher.rate_limiter.release()
        except Exception as exc:  # noqa: BLE001
            emit(on_progress, "error", f"GitHub search failed: {exc}")  # type: ignore[arg-type]
            return []
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []
        found: list[RawCandidate] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("html_url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue
            body = str(item.get("body") or "")
            published = _parse_github_time(
                item.get("created_at") or item.get("updated_at")
            )
            found.append(
                RawCandidate(
                    source_kind="github_issues",
                    source_name="GitHub issues",
                    source_category="p1_intent",
                    listing_id=f"gh:{item.get('id') or url}"[:512],
                    url=url[:2048],
                    title=title[:512],
                    description=body[:4000],
                    excerpt=(body or title)[:400],
                    published_at=published,
                )
            )
        emit(on_progress, "ok", f"GitHub: {len(found)} open issue(s)")  # type: ignore[arg-type]
        return found


def _parse_github_time(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    return published
