"""Public SearXNG directory helpers (https://searx.space/).

searx.space is a directory of community instances — not a search engine itself.
Most public instances disable JSON and/or block bots; local SearXNG remains the
reliable research path. We still try healthy public instances as optional failover.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.contacts.ssrf import is_safe_public_http_url

logger = logging.getLogger(__name__)

DIRECTORY_URL = "https://searx.space/data/instances.json"
_CACHE_PATH = Path(".cache/searx_space_cache.json")
_CACHE_TTL_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class PublicInstance:
    url: str
    success_pct: float
    median_s: float | None


def _normalize_base(url: str) -> str:
    return url.strip().rstrip("/")


def load_cached_instances(*, max_age_s: float = _CACHE_TTL_SECONDS) -> list[PublicInstance] | None:
    if not _CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(_CACHE_PATH.read_text())
        fetched_at = float(payload.get("fetched_at") or 0)
        if time.time() - fetched_at > max_age_s:
            return None
        rows = []
        for item in payload.get("instances") or []:
            if not isinstance(item, dict):
                continue
            url = _normalize_base(str(item.get("url") or ""))
            if not url:
                continue
            rows.append(
                PublicInstance(
                    url=url,
                    success_pct=float(item.get("success_pct") or 0),
                    median_s=(
                        float(item["median_s"])
                        if item.get("median_s") is not None
                        else None
                    ),
                )
            )
        return rows
    except Exception:
        logger.debug("searx.space cache unreadable", exc_info=True)
        return None


def save_cached_instances(rows: list[PublicInstance]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps(
                {
                    "fetched_at": time.time(),
                    "source": DIRECTORY_URL,
                    "instances": [
                        {
                            "url": r.url,
                            "success_pct": r.success_pct,
                            "median_s": r.median_s,
                        }
                        for r in rows
                    ],
                },
                indent=2,
            )
        )
    except Exception:
        logger.debug("could not write searx.space cache", exc_info=True)


def fetch_public_instances(*, limit: int = 12, timeout: float = 25.0) -> list[PublicInstance]:
    """Fetch healthy clearnet instances from searx.space (cached on disk)."""
    cached = load_cached_instances()
    if cached is not None:
        return cached[:limit]

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(DIRECTORY_URL)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("searx.space directory fetch failed: %s", exc)
        cached_stale = load_cached_instances(max_age_s=7 * 24 * 3600)
        return (cached_stale or [])[:limit]

    instances = data.get("instances") if isinstance(data, dict) else None
    if not isinstance(instances, dict):
        return []

    rows: list[PublicInstance] = []
    for url, meta in instances.items():
        if not isinstance(meta, dict):
            continue
        if meta.get("network_type") != "normal":
            continue
        if meta.get("error"):
            continue
        http_meta = meta.get("http") if isinstance(meta.get("http"), dict) else {}
        if http_meta.get("status_code") != 200:
            continue
        timing = meta.get("timing") if isinstance(meta.get("timing"), dict) else {}
        search = timing.get("search") if isinstance(timing.get("search"), dict) else {}
        success = float(search.get("success_percentage") or 0)
        if success < 80:
            continue
        all_stats = search.get("all") if isinstance(search.get("all"), dict) else {}
        median = all_stats.get("median")
        base = _normalize_base(str(url))
        if not base.startswith("https://"):
            continue
        if not is_safe_public_http_url(base + "/"):
            continue
        rows.append(
            PublicInstance(
                url=base,
                success_pct=success,
                median_s=float(median) if median is not None else None,
            )
        )

    rows.sort(key=lambda r: (-r.success_pct, r.median_s if r.median_s is not None else 99.0))
    save_cached_instances(rows)
    return rows[:limit]


def resolve_searx_bases(
    *,
    primary_url: str,
    extra_urls: list[str],
    use_public_directory: bool,
    public_limit: int = 3,
) -> list[str]:
    """Ordered unique SearXNG bases: local/primary first, then extras, then directory."""
    bases: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        base = _normalize_base(url)
        if not base:
            return
        host = (urlparse(base).hostname or "").casefold()
        key = base.casefold()
        if key in seen:
            return
        if host in {"localhost", "127.0.0.1"}:
            bases.append(base)
            seen.add(key)
            return
        if not is_safe_public_http_url(base if base.endswith("/") else base + "/"):
            return
        bases.append(base)
        seen.add(key)

    add(primary_url)
    for url in extra_urls:
        add(url)
    if use_public_directory:
        for row in fetch_public_instances(limit=max(1, public_limit)):
            add(row.url)
    return bases


def parse_extra_urls(raw: str) -> list[str]:
    return [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]


def directory_summary(limit: int = 8) -> list[dict[str, Any]]:
    """Compact rows for Settings / Discover UI."""
    return [
        {
            "url": row.url,
            "success_pct": row.success_pct,
            "median_s": row.median_s,
        }
        for row in fetch_public_instances(limit=limit)
    ]
