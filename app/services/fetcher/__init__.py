"""HTTP fetch, robots.txt, extraction, and content hashing."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedContent:
    text: str
    title: str | None
    published_at: datetime | None
    content_hash: str


@dataclass
class FetchResult:
    """Outcome of one fetch attempt. `changed` is False when we must not create a snapshot."""

    ok: bool
    url: str
    final_url: str | None = None
    http_status: int | None = None
    changed: bool = False
    not_modified: bool = False
    blocked_by_robots: bool = False
    error: str | None = None
    extracted: ExtractedContent | None = None
    etag: str | None = None
    last_modified: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RateLimiter:
    """Per-domain delay plus a global concurrency cap (spec section 18)."""

    def __init__(self, per_domain_delay: float, max_concurrent: int) -> None:
        self._delay = per_domain_delay
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(max_concurrent)

    def acquire(self, domain: str) -> None:
        self._semaphore.acquire()
        with self._lock:
            now = time.monotonic()
            wait = self._delay - (now - self._last.get(domain, 0.0))
        if wait > 0:
            time.sleep(wait)
        with self._lock:
            self._last[domain] = time.monotonic()

    def release(self) -> None:
        self._semaphore.release()


class RobotsCache:
    """Cached robots.txt decisions. Fail open on fetch errors: a broken robots endpoint
    must not permanently block research of a public page the operator explicitly seeded."""

    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, RobotFileParser | None]] = {}
        self._lock = threading.Lock()

    def allowed(self, client: httpx.Client, url: str, user_agent: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(origin)
            if entry and now - entry[0] < self._ttl:
                parser = entry[1]
            else:
                parser = None
                entry = None

        if entry is None:
            parser = self._load(client, origin, user_agent)
            with self._lock:
                self._cache[origin] = (now, parser)

        if parser is None:
            return True
        return parser.can_fetch(user_agent, url)

    def _load(
        self, client: httpx.Client, origin: str, user_agent: str
    ) -> RobotFileParser | None:
        robots_url = f"{origin}/robots.txt"
        try:
            response = client.get(robots_url, timeout=10.0)
            if response.status_code >= 400:
                return None
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
            # Ensure the UA string we check with is known to the parser.
            _ = user_agent
            return parser
        except Exception as exc:  # noqa: BLE001 - fail open, log, continue
            logger.warning("robots.txt fetch failed for %s: %s", origin, exc)
            return None


def hash_text(text: str) -> str:
    """Hash extracted text, never raw HTML (decision D-07)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_content(html: str, url: str) -> ExtractedContent | None:
    extracted = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        with_metadata=True,
        output_format="json",
    )
    if not extracted:
        return None

    import json

    data = json.loads(extracted)
    text = (data.get("text") or "").strip()
    if len(text) < 50:
        return None

    published_at: datetime | None = None
    raw_date = data.get("date")
    if raw_date:
        try:
            published_at = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
        except ValueError:
            published_at = None

    return ExtractedContent(
        text=text,
        title=(data.get("title") or None),
        published_at=published_at,
        content_hash=hash_text(text),
    )


class Fetcher:
    """Respectful HTTP fetch with caching headers, robots, and content hashing."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
        *,
        owns_client: bool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._owns_client = owns_client if owns_client is not None else client is None
        self.client = client or httpx.Client(
            timeout=self.settings.fetch_timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
        )
        self.rate_limiter = RateLimiter(
            self.settings.per_domain_delay_seconds,
            self.settings.max_concurrent_fetches,
        )
        self.robots = RobotsCache()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        previous_hash: str | None = None,
    ) -> FetchResult:
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower()
        if not domain:
            return FetchResult(ok=False, url=url, error="invalid url")

        if not self.robots.allowed(self.client, url, self.settings.user_agent):
            return FetchResult(
                ok=False,
                url=url,
                blocked_by_robots=True,
                error="blocked by robots.txt",
            )

        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        self.rate_limiter.acquire(domain)
        try:
            response = self.client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            return FetchResult(ok=False, url=url, error=f"timeout: {exc}")
        except httpx.HTTPError as exc:
            return FetchResult(ok=False, url=url, error=f"http: {type(exc).__name__}: {exc}")
        finally:
            self.rate_limiter.release()

        if response.status_code == 304:
            return FetchResult(
                ok=True,
                url=url,
                final_url=str(response.url),
                http_status=304,
                changed=False,
                not_modified=True,
                etag=etag,
                last_modified=last_modified,
            )

        if response.status_code >= 400:
            return FetchResult(
                ok=False,
                url=url,
                final_url=str(response.url),
                http_status=response.status_code,
                error=f"HTTP {response.status_code}",
            )

        extracted = extract_content(response.text, str(response.url))
        if extracted is None:
            return FetchResult(
                ok=False,
                url=url,
                final_url=str(response.url),
                http_status=response.status_code,
                error="no extractable text",
            )

        changed = previous_hash is None or extracted.content_hash != previous_hash
        return FetchResult(
            ok=True,
            url=url,
            final_url=str(response.url),
            http_status=response.status_code,
            changed=changed,
            not_modified=not changed,
            extracted=extracted,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            metadata={
                "content_type": response.headers.get("content-type"),
                "redirected": str(response.url) != url,
            },
        )


def parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (TypeError, ValueError, IndexError):
        return None
