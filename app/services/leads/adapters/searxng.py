"""Optional self-hosted SearXNG JSON search — never scrapes Google."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from app.config import Settings
from app.services.contacts.ssrf import is_safe_public_http_url
from app.services.fetcher import Fetcher
from app.services.leads.adapters.base import (
    AdapterCapability,
    RawCandidate,
    emit,
)
from app.services.leads.filters import TargetingFilters, build_search_queries


class SearxngAdapter:
    key = "searxng"

    def capability(self, settings: Settings) -> AdapterCapability:
        configured = bool((settings.searxng_url or "").strip())
        return AdapterCapability(
            key=self.key,
            label="SearXNG (self-hosted search)",
            category="p2_business",
            description=(
                "Optional metasearch you host. Uses the documented JSON API. "
                "Results are candidates — pages are not treated as verified leads."
            ),
            availability="optional_config" if not configured else "available",
            requires_config="SEARXNG_URL",
            limitations="You must run SearXNG. Do not point this at Google HTML.",
            priority=25,
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
        base = (settings.searxng_url or "").strip().rstrip("/")
        if not base:
            emit(on_progress, "warn", "SearXNG skipped — SEARXNG_URL is not set")  # type: ignore[arg-type]
            return []
        host = (urlparse(base).hostname or "").casefold()
        if host not in {"localhost", "127.0.0.1"} and not is_safe_public_http_url(base):
            emit(on_progress, "error", "SearXNG URL failed safety checks")  # type: ignore[arg-type]
            return []
        queries = build_search_queries(filters)[:2]
        found: list[RawCandidate] = []
        seen: set[str] = set()
        search_url = urljoin(base + "/", "search")
        host = urlparse(base).hostname or "searxng"
        for query in queries:
            emit(on_progress, "info", f'SearXNG: “{query.text}”')  # type: ignore[arg-type]
            try:
                fetcher.rate_limiter.acquire(host)
                try:
                    response = fetcher.client.get(
                        search_url,
                        params={"q": query.text, "format": "json", "categories": "general"},
                    )
                    response.raise_for_status()
                    payload = response.json()
                finally:
                    fetcher.rate_limiter.release()
            except Exception as exc:  # noqa: BLE001
                emit(on_progress, "error", f"SearXNG failed: {exc}")  # type: ignore[arg-type]
                continue
            results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(results, list):
                continue
            for row in results:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                title = str(row.get("title") or "").strip()
                if not url or not title or url in seen:
                    continue
                if not is_safe_public_http_url(url):
                    continue
                seen.add(url)
                content = str(row.get("content") or "")
                found.append(
                    RawCandidate(
                        source_kind="searxng",
                        source_name="SearXNG",
                        source_category="p2_business",
                        listing_id=f"searx:{url}"[:512],
                        url=url[:2048],
                        title=title[:512],
                        description=content[:4000],
                        excerpt=(content or title)[:400],
                    )
                )
                if len(found) >= limit:
                    return found
        emit(on_progress, "ok", f"SearXNG: {len(found)} result(s)")  # type: ignore[arg-type]
        return found
