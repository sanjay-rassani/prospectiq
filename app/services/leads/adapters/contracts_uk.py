"""UK Contracts Finder public search (no API key)."""

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

CONTRACTS_SEARCH = (
    "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
)


class ContractsUkAdapter:
    key = "contracts_uk"

    def capability(self, settings: Settings) -> AdapterCapability:
        return AdapterCapability(
            key=self.key,
            label="UK Contracts Finder",
            category="p1_intent",
            description=(
                "Public UK government procurement notices (OCDS search). "
                "High-intent tenders for software, data, and digital services."
            ),
            availability="available",
            limitations="UK public-sector notices only. Response shape may vary.",
            priority=15,
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
        queries = [q.text for q in build_search_queries(filters) if q.intent == "high_intent"]
        if not queries:
            queries = ["software development", "digital services"]
        keyword = queries[0][:180]
        emit(on_progress, "info", f'Contracts Finder: “{keyword}”')  # type: ignore[arg-type]
        body = {
            "searchCriteria": {"keyword": keyword},
            "size": min(limit, 25),
        }
        try:
            fetcher.rate_limiter.acquire("www.contractsfinder.service.gov.uk")
            try:
                response = fetcher.client.post(
                    CONTRACTS_SEARCH,
                    json=body,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
            finally:
                fetcher.rate_limiter.release()
        except Exception as exc:  # noqa: BLE001
            emit(on_progress, "error", f"Contracts Finder failed: {exc}")  # type: ignore[arg-type]
            return []

        items = _extract_items(payload)
        max_age = int(getattr(filters, "max_age_days", 0) or 0)
        cutoff = datetime.now(UTC) - timedelta(days=max_age) if max_age > 0 else None
        found: list[RawCandidate] = []
        for item in items[: limit * 2]:
            cand = _from_item(item)
            if not cand:
                continue
            if cutoff is not None and cand.published_at is not None:
                pub = cand.published_at
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=UTC)
                if pub < cutoff:
                    continue
            found.append(cand)
            if len(found) >= limit:
                break
        emit(on_progress, "ok", f"Contracts Finder: {len(found)} notice(s)")  # type: ignore[arg-type]
        return found


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("noticeList", "results", "releases", "items", "documents"):
        value = payload.get(key)
        if isinstance(value, list):
            out: list[dict[str, Any]] = []
            for row in value:
                if isinstance(row, dict):
                    inner = row.get("item") if isinstance(row.get("item"), dict) else row
                    if isinstance(inner, dict):
                        out.append(inner)
            return out
    return []


def _from_item(item: dict[str, Any]) -> RawCandidate | None:
    title = str(
        item.get("title")
        or item.get("noticeTitle")
        or (item.get("tender") or {}).get("title")
        or ""
    ).strip()
    url = str(
        item.get("url")
        or item.get("link")
        or item.get("htmlUrl")
        or item.get("noticeUrl")
        or ""
    ).strip()
    ocid = str(item.get("ocid") or item.get("id") or item.get("noticeId") or "").strip()
    if not url and ocid:
        url = (
            "https://www.contractsfinder.service.gov.uk/Notice/"
            + ocid.replace("ocds-b5fd17-", "")
        )
    if not title or not url:
        return None
    description = str(
        item.get("description")
        or item.get("summary")
        or (item.get("tender") or {}).get("description")
        or ""
    )
    published: datetime | None = None
    raw_date = item.get("publishedDate") or item.get("date") or item.get("releasedate")
    if isinstance(raw_date, str):
        try:
            published = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
        except ValueError:
            published = None
    value = item.get("value") or item.get("estimatedValue") or {}
    budget = None
    if isinstance(value, dict):
        amount = value.get("amount") or value.get("minValue")
        currency = value.get("currency") or "GBP"
        if amount:
            budget = f"{amount} {currency}"
    elif isinstance(value, (int, float, str)) and str(value).strip():
        budget = str(value)
    listing = ocid or url
    return RawCandidate(
        source_kind="contracts_uk",
        source_name="UK Contracts Finder",
        source_category="p1_intent",
        listing_id=f"ukcf:{listing}"[:512],
        url=url[:2048],
        title=title[:512],
        description=description[:4000],
        excerpt=(description or title)[:400],
        location=str(item.get("region") or item.get("location") or "")[:255] or None,
        budget_text=budget[:128] if budget else None,
        contract_type=str(item.get("type") or item.get("noticeType") or "")[:64] or None,
        published_at=published,
        extra={"ocid": ocid},
    )
