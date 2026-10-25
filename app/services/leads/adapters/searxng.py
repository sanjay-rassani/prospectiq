"""SearXNG research — local and/or public instances from searx.space.

Never scrapes Google HTML. Queries SearXNG JSON API, then visits public result pages.
Public community instances (listed on https://searx.space/) often disable JSON or block
bots; local docker compose SearXNG is the reliable path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from app.config import Settings
from app.services.buyers.guardrails import is_blocked_fetch_host
from app.services.contacts.ssrf import is_safe_public_http_url
from app.services.fetcher import Fetcher
from app.services.leads.adapters.base import (
    AdapterCapability,
    RawCandidate,
    emit,
)
from app.services.leads.filters import (
    TargetingFilters,
    build_search_queries,
    searx_time_range,
)
from app.services.leads.scoring import is_supplier_noise
from app.services.leads.searx_directory import parse_extra_urls, resolve_searx_bases

# Do not "research" SERPs or code/marketplace hosts — those are not buyer companies.
_SKIP_VISIT_HOSTS = frozenset(
    {
        "google.com",
        "www.google.com",
        "google.co.uk",
        "bing.com",
        "www.bing.com",
        "duckduckgo.com",
        "www.duckduckgo.com",
        "search.brave.com",
        "brave.com",
        "startpage.com",
        "www.startpage.com",
        "qwant.com",
        "www.qwant.com",
        "yahoo.com",
        "search.yahoo.com",
        "yandex.com",
        "yandex.ru",
        "facebook.com",
        "www.facebook.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "youtube.com",
        "www.youtube.com",
        "github.com",
        "www.github.com",
        "gist.github.com",
        "gitlab.com",
        "www.gitlab.com",
        "npmjs.com",
        "www.npmjs.com",
        "upwork.com",
        "www.upwork.com",
        "fiverr.com",
        "www.fiverr.com",
    }
)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold()


def _should_visit(url: str, *, title: str = "") -> bool:
    if not is_safe_public_http_url(url):
        return False
    if is_blocked_fetch_host(url):
        return False
    if is_supplier_noise(url=url, title=title):
        return False
    host = _host(url)
    if not host:
        return False
    if host in _SKIP_VISIT_HOSTS:
        return False
    return not any(host.endswith("." + blocked) for blocked in _SKIP_VISIT_HOSTS)


def _looks_like_bot_wall(text: str) -> bool:
    t = (text or "").casefold()
    return (
        "making sure you're not a bot" in t
        or "making sure you&#39;re not a bot" in t
        or "cf-browser-verification" in t
        or ("attention required" in t and "cloudflare" in t)
    )


class SearxngAdapter:
    key = "searxng"

    def capability(self, settings: Settings) -> AdapterCapability:
        primary = bool((settings.searxng_url or "").strip())
        extras = bool((settings.searxng_extra_urls or "").strip())
        public = bool(settings.searxng_use_public_directory)
        configured = primary or extras or public
        return AdapterCapability(
            key=self.key,
            label="SearXNG (search research)",
            category="p2_business",
            description=(
                "Research via SearXNG: your local instance and/or public instances from "
                "searx.space, then visit public result pages. Never scrapes Google HTML."
            ),
            availability="optional_config" if not configured else "available",
            requires_config="SEARXNG_URL (recommended) or public directory",
            limitations=(
                "Public searx.space instances often block bots / disable JSON. "
                "Prefer local docker compose SearXNG."
            ),
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
        use_public = bool(
            getattr(filters, "use_public_searxng", None)
            if getattr(filters, "use_public_searxng", None) is not None
            else settings.searxng_use_public_directory
        )
        bases = resolve_searx_bases(
            primary_url=settings.searxng_url or "",
            extra_urls=parse_extra_urls(settings.searxng_extra_urls or ""),
            use_public_directory=use_public,
            public_limit=max(1, int(settings.searxng_public_max_instances or 3)),
        )
        if not bases:
            emit(  # type: ignore[arg-type]
                on_progress,
                "warn",
                "SearXNG skipped — set SEARXNG_URL and/or enable searx.space directory",
            )
            return []

        emit(  # type: ignore[arg-type]
            on_progress,
            "info",
            f"SearXNG bases ({len(bases)}): " + ", ".join(bases[:6])
            + ("…" if len(bases) > 6 else ""),
        )

        hits: list[dict[str, str]] = []
        for base in bases:
            emit(on_progress, "info", f"Trying SearXNG instance {base}")  # type: ignore[arg-type]
            part = self._search_hits(
                filters=filters,
                fetcher=fetcher,
                base=base,
                on_progress=on_progress,
                limit=max(limit * 2, limit),
            )
            if part:
                hits = part
                emit(on_progress, "ok", f"Using results from {base} ({len(hits)} hit(s))")  # type: ignore[arg-type]
                break
        if not hits:
            emit(  # type: ignore[arg-type]
                on_progress,
                "warn",
                "SearXNG: no usable hits from local/public instances "
                "(public ones often block bots — keep local SearXNG on :8080)",
            )
            return []

        emit(  # type: ignore[arg-type]
            on_progress,
            "info",
            f"SearXNG: researching up to {min(limit, len(hits))} public page(s)…",
        )
        found: list[RawCandidate] = []
        visited = 0
        for hit in hits:
            if len(found) >= limit:
                break
            url = hit["url"]
            title = hit["title"]
            snippet = hit["snippet"]
            if is_supplier_noise(url=url, title=title):
                emit(  # type: ignore[arg-type]
                    on_progress,
                    "info",
                    f"Skipped repo/marketplace noise: {title[:60]}",
                )
                continue
            if not _should_visit(url, title=title):
                continue

            visited += 1
            emit(on_progress, "info", f"Visiting [{visited}] {url}")  # type: ignore[arg-type]
            page_text = ""
            final_url = url
            try:
                result = fetcher.fetch(url)
            except Exception as exc:  # noqa: BLE001
                emit(on_progress, "warn", f"Visit failed {url} — {exc}")  # type: ignore[arg-type]
                result = None
            if result is not None and result.ok and result.extracted is not None:
                page_text = (result.extracted.text or "").strip()
                final_url = result.final_url or url
                emit(  # type: ignore[arg-type]
                    on_progress,
                    "ok",
                    f"Read {len(page_text)} chars · {final_url}",
                )
            elif result is not None:
                reason = result.error or "unreadable"
                if result.blocked_by_robots:
                    reason = "robots.txt"
                emit(on_progress, "warn", f"Could not read page — {reason}")  # type: ignore[arg-type]

            description = page_text[:8000] if page_text else snippet[:4000]
            if page_text and snippet:
                description = (page_text[:7000] + "\n\n[search snippet]\n" + snippet)[:8000]
            published = None
            if result is not None and result.ok and result.extracted is not None:
                published = result.extracted.published_at
            if published is None:
                published = _parse_searx_date(hit.get("published") or "")
            found.append(
                RawCandidate(
                    source_kind="searxng",
                    source_name="SearXNG research",
                    source_category="p2_business",
                    listing_id=f"searx:{final_url}"[:512],
                    url=final_url[:2048],
                    title=title[:512],
                    description=description,
                    excerpt=(page_text or snippet or title)[:400],
                    published_at=published,
                    extra={
                        "researched": bool(page_text),
                        "search_url": url,
                        "query": hit.get("query") or "",
                        "via": hit.get("via") or "",
                    },
                )
            )

        researched = sum(1 for c in found if c.extra.get("researched"))
        emit(  # type: ignore[arg-type]
            on_progress,
            "ok",
            f"SearXNG research: {len(found)} candidate(s), {researched} page(s) read",
        )
        return found

    def _search_hits(
        self,
        *,
        filters: TargetingFilters,
        fetcher: Fetcher,
        base: str,
        on_progress: object,
        limit: int,
    ) -> list[dict[str, str]]:
        host = (urlparse(base).hostname or "").casefold()
        if host not in {"localhost", "127.0.0.1"} and not is_safe_public_http_url(
            base if base.endswith("/") else base + "/"
        ):
            emit(on_progress, "warn", f"Skipped unsafe SearXNG URL: {base}")  # type: ignore[arg-type]
            return []

        queries = build_search_queries(filters)[:3]
        # Drop code-index engines even if old prefs still list them.
        _noisy_engines = frozenset({"github", "wikipedia", "npm", "gitlab"})
        engine_list = [
            e for e in (filters.search_engines or []) if e and e not in _noisy_engines
        ]
        engines = ",".join(engine_list)
        time_range = searx_time_range(int(getattr(filters, "max_age_days", 0) or 0))
        hits: list[dict[str, str]] = []
        seen: set[str] = set()
        search_url = urljoin(base + "/", "search")
        api_host = urlparse(base).hostname or "searxng"
        for query in queries:
            engine_note = f" via {engines}" if engines else ""
            age_note = f" · {time_range}" if time_range else ""
            emit(  # type: ignore[arg-type]
                on_progress,
                "info",
                f'SearXNG{engine_note}{age_note}: “{query.text}” @ {api_host}',
            )
            try:
                fetcher.rate_limiter.acquire(api_host)
                try:
                    params: dict[str, str] = {
                        "q": query.text,
                        "format": "json",
                        "categories": "general",
                    }
                    if engines:
                        params["engines"] = engines
                    if time_range:
                        params["time_range"] = time_range
                    response = fetcher.client.get(
                        search_url,
                        params=params,
                        headers={"Accept": "application/json"},
                    )
                    body_preview = (response.text or "")[:400]
                    if response.status_code in {403, 429} or _looks_like_bot_wall(body_preview):
                        emit(  # type: ignore[arg-type]
                            on_progress,
                            "warn",
                            f"{api_host}: blocked or JSON disabled (HTTP {response.status_code})",
                        )
                        return []
                    if response.status_code == 404:
                        emit(on_progress, "warn", f"{api_host}: search endpoint not found")  # type: ignore[arg-type]
                        return []
                    response.raise_for_status()
                    # Bot walls sometimes return 200 HTML.
                    ctype = (response.headers.get("content-type") or "").casefold()
                    not_json = "application/json" not in ctype
                    bad_body = _looks_like_bot_wall(body_preview) or (
                        not body_preview.lstrip().startswith("{")
                    )
                    if not_json and bad_body:
                        emit(  # type: ignore[arg-type]
                            on_progress,
                            "warn",
                            f"{api_host}: did not return JSON (bot wall or HTML-only)",
                        )
                        return []
                    payload = response.json()
                finally:
                    fetcher.rate_limiter.release()
            except Exception as exc:  # noqa: BLE001
                emit(on_progress, "warn", f"{api_host} failed: {exc}")  # type: ignore[arg-type]
                return []
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
                if is_supplier_noise(url=url, title=title):
                    continue
                seen.add(url)
                published_raw = row.get("publishedDate") or row.get("pubdate") or ""
                hits.append(
                    {
                        "url": url[:2048],
                        "title": title[:512],
                        "snippet": str(row.get("content") or "")[:2000],
                        "query": query.text,
                        "via": base,
                        "published": str(published_raw or ""),
                    }
                )
                if len(hits) >= limit:
                    return hits
        return hits


def _parse_searx_date(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        published = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    return published
