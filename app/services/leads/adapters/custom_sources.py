"""Operator-added public RSS/Atom URLs from Discover prefs (not marketplace scrapers)."""

from __future__ import annotations

from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from app.config import Settings
from app.services.contacts.ssrf import is_safe_public_http_url
from app.services.fetcher import Fetcher
from app.services.leads.adapters.base import (
    AdapterCapability,
    RawCandidate,
    emit,
)
from app.services.leads.filters import TargetingFilters


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _parse_feed(xml_text: str, *, source_name: str, limit: int) -> list[RawCandidate]:
    root = ET.fromstring(xml_text)
    found: list[RawCandidate] = []
    entries = [
        el
        for el in root.iter()
        if _local(el.tag) in {"item", "entry"}
    ]
    for el in entries:
        title = ""
        link = ""
        summary = ""
        published = None
        for child in el:
            name = _local(child.tag)
            if name == "title" and child.text:
                title = child.text.strip()
            elif name == "link":
                href = (child.attrib.get("href") or "").strip()
                if href:
                    link = href
                elif child.text and child.text.strip().startswith("http"):
                    link = child.text.strip()
            elif name in {"description", "summary", "content"} and child.text:
                summary = (summary or child.text.strip())[:4000]
            elif name in {"pubDate", "published", "updated"} and child.text:
                try:
                    published = parsedate_to_datetime(child.text.strip())
                except (TypeError, ValueError, IndexError):
                    published = None
        if not link or not is_safe_public_http_url(link):
            continue
        found.append(
            RawCandidate(
                source_kind="custom_sources",
                source_name=source_name[:120] or "Custom source",
                source_category="p4_other",
                listing_id=f"custom:{link}"[:512],
                url=link[:2048],
                title=(title or link)[:512],
                description=summary,
                excerpt=(summary or title or "")[:400],
                published_at=published,
            )
        )
        if len(found) >= limit:
            break
    return found


class CustomSourcesAdapter:
    key = "custom_sources"

    def capability(self, settings: Settings) -> AdapterCapability:
        return AdapterCapability(
            key=self.key,
            label="Your custom sources",
            category="p4_other",
            description=(
                "Public RSS/Atom feeds you add on Discover. "
                "Use this for niche boards, changelogs, or partner feeds."
            ),
            availability="available",
            limitations="Only public feed URLs. No login walls or marketplace scrapers.",
            priority=35,
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
        sources = [
            s
            for s in (filters.custom_sources or [])
            if (s.get("url") or "").strip() and (s.get("kind") or "rss") in {"rss", "atom"}
        ]
        if not sources:
            emit(on_progress, "warn", "Custom sources: none configured")  # type: ignore[arg-type]
            return []
        found: list[RawCandidate] = []
        per = max(3, limit // max(len(sources), 1))
        for src in sources:
            name = str(src.get("name") or "Custom").strip() or "Custom"
            url = str(src.get("url") or "").strip()
            if not is_safe_public_http_url(url):
                emit(on_progress, "warn", f"Skipped unsafe custom URL: {name}")  # type: ignore[arg-type]
                continue
            emit(on_progress, "info", f"Custom source: {name}")  # type: ignore[arg-type]
            try:
                host = url.split("/")[2] if "://" in url else "custom"
                fetcher.rate_limiter.acquire(host)
                try:
                    response = fetcher.client.get(url)
                    response.raise_for_status()
                    text = response.text
                finally:
                    fetcher.rate_limiter.release()
            except Exception as exc:  # noqa: BLE001
                emit(on_progress, "error", f"{name} failed: {exc}")  # type: ignore[arg-type]
                continue
            try:
                batch = _parse_feed(text, source_name=name, limit=per)
            except ET.ParseError as exc:
                emit(on_progress, "error", f"{name}: not a valid feed ({exc})")  # type: ignore[arg-type]
                continue
            found.extend(batch)
            if len(found) >= limit:
                break
        emit(on_progress, "ok", f"Custom sources: {len(found)} item(s)")  # type: ignore[arg-type]
        return found[:limit]
