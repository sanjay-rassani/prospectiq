"""End-to-end seed and refresh against a mocked HTTP stack (FR-01, FR-02, FR-03, AC-2, AC-3)."""

from __future__ import annotations

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Company, SourceSnapshot
from app.services.discovery.seed import refresh_company, seed_targets
from app.services.fetcher import Fetcher

HTML_V1 = """<!DOCTYPE html><html><head><title>Acme</title></head>
<body><article><h1>Acme Logistics</h1>
<p>Acme Logistics runs three UK depots and still reconciles inventory in Excel every night.
Growth has pushed daily shipments past one thousand.</p></article></body></html>"""

HTML_V2 = HTML_V1.replace("one thousand", "two thousand")


def _fetcher(html_by_path: dict[str, str] | None = None, *, status: int = 200) -> Fetcher:
    pages = html_by_path or {"/": HTML_V1}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.headers.get("if-none-match") == '"v1"' and status == 304:
            return httpx.Response(304)
        body = pages.get(request.url.path, pages.get("/", HTML_V1))
        return httpx.Response(status, text=body, headers={"ETag": '"v1"'})

    settings = Settings(per_domain_delay_seconds=0.0, max_concurrent_fetches=4)
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return Fetcher(settings=settings, client=client, owns_client=True)


def test_seed_stores_snapshot_and_dedupes_domain(session: Session) -> None:
    fetcher = _fetcher()
    outcomes = seed_targets(
        session,
        "Acme | https://www.acme-test.example/\nhttps://acme-test.example/about",
        fetcher=fetcher,
    )
    # Second line shares the domain; parse_seed_blob keeps the first only.
    assert len(outcomes) == 1
    assert outcomes[0].created
    assert outcomes[0].snapshot is not None

    companies = session.scalars(select(Company)).all()
    assert len(companies) == 1
    assert companies[0].domain == "acme-test.example"

    count = session.scalar(select(func.count()).select_from(SourceSnapshot))
    assert count == 1


def test_refresh_unchanged_does_not_create_duplicate_snapshot(session: Session) -> None:
    fetcher = _fetcher()
    seeded = seed_targets(session, "https://acme-test.example/", fetcher=fetcher)
    company = seeded[0].company
    assert seeded[0].snapshot is not None

    again = refresh_company(session, company.id, fetcher=_fetcher())
    assert again.snapshot is None
    assert "unchanged" in again.message

    count = session.scalar(select(func.count()).select_from(SourceSnapshot))
    assert count == 1


def test_refresh_changed_creates_snapshot_with_previous_hash(session: Session) -> None:
    seeded = seed_targets(
        session, "https://acme-test.example/", fetcher=_fetcher({"/": HTML_V1})
    )
    company = seeded[0].company
    first_hash = seeded[0].snapshot.content_hash  # type: ignore[union-attr]

    refreshed = refresh_company(
        session, company.id, fetcher=_fetcher({"/": HTML_V2})
    )
    assert refreshed.snapshot is not None
    assert refreshed.snapshot.previous_hash == first_hash
    assert refreshed.snapshot.content_hash != first_hash

    count = session.scalar(select(func.count()).select_from(SourceSnapshot))
    assert count == 2


def test_refresh_304_skips_snapshot(session: Session) -> None:
    seeded = seed_targets(session, "https://acme-test.example/", fetcher=_fetcher())
    company = seeded[0].company

    outcome = refresh_company(
        session, company.id, fetcher=_fetcher(status=304)
    )
    assert outcome.fetch.http_status == 304
    assert outcome.snapshot is None
    assert session.scalar(select(func.count()).select_from(SourceSnapshot)) == 1
