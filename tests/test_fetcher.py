"""Fetcher tests with httpx MockTransport (P2-11)."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from app.config import Settings
from app.services.fetcher import Fetcher, extract_content, hash_text

SAMPLE_HTML = """<!DOCTYPE html>
<html><head><title>Acme Warehouse Launch</title></head>
<body>
<article>
  <h1>Acme opens a second warehouse</h1>
  <p>Acme Logistics has opened a second warehouse in Manchester to handle growth.
  Daily orders have risen from 400 to 1,200. Operations still run on shared Excel
  spreadsheets that depot managers reconcile by hand each evening.</p>
  <p>We are reviewing options for a warehouse management system that can scale
  across sites without the nightly spreadsheet ritual.</p>
</article>
</body></html>
"""

CHANGED_HTML = SAMPLE_HTML.replace("1,200", "2,000")


def _settings() -> Settings:
    return Settings(
        per_domain_delay_seconds=0.0,
        max_concurrent_fetches=4,
        fetch_timeout_seconds=5.0,
        user_agent="ProspectingEngine-Test/0.1",
    )


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_hash_is_over_extracted_text_not_html() -> None:
    a = extract_content(SAMPLE_HTML, "https://acme.example/")
    b = extract_content(
        SAMPLE_HTML.replace("<h1>", '<h1 data-csrf="abc123">'),
        "https://acme.example/",
    )
    assert a is not None and b is not None
    assert a.content_hash == b.content_hash
    assert a.content_hash == hash_text(a.text)


def test_new_snapshot_on_first_fetch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=SAMPLE_HTML, headers={"ETag": '"v1"'})

    client = httpx.Client(transport=_transport(handler), follow_redirects=True)
    with Fetcher(settings=_settings(), client=client, owns_client=True) as fetcher:
        result = fetcher.fetch("https://acme.example/")
    assert result.ok
    assert result.changed
    assert result.http_status == 200
    assert result.extracted is not None
    assert "second warehouse" in result.extracted.text
    assert result.etag == '"v1"'


def test_unchanged_content_is_not_marked_changed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=SAMPLE_HTML)

    first_hash: str
    client = httpx.Client(transport=_transport(handler), follow_redirects=True)
    with Fetcher(settings=_settings(), client=client, owns_client=False) as fetcher:
        first = fetcher.fetch("https://acme.example/")
        assert first.extracted is not None
        first_hash = first.extracted.content_hash
        second = fetcher.fetch("https://acme.example/", previous_hash=first_hash)
    client.close()
    assert second.ok
    assert not second.changed
    assert second.not_modified


def test_304_not_modified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, text=SAMPLE_HTML, headers={"ETag": '"v1"'})

    client = httpx.Client(transport=_transport(handler), follow_redirects=True)
    with Fetcher(settings=_settings(), client=client, owns_client=True) as fetcher:
        result = fetcher.fetch(
            "https://acme.example/", etag='"v1"', previous_hash="abc"
        )
    assert result.ok
    assert result.not_modified
    assert result.http_status == 304
    assert not result.changed


def test_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(404, text="missing")

    client = httpx.Client(transport=_transport(handler), follow_redirects=True)
    with Fetcher(settings=_settings(), client=client, owns_client=True) as fetcher:
        result = fetcher.fetch("https://acme.example/missing")
    assert not result.ok
    assert result.http_status == 404


def test_redirect_chain_uses_final_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/old":
            return httpx.Response(302, headers={"Location": "https://acme.example/new"})
        return httpx.Response(200, text=SAMPLE_HTML)

    client = httpx.Client(transport=_transport(handler), follow_redirects=True)
    with Fetcher(settings=_settings(), client=client, owns_client=True) as fetcher:
        result = fetcher.fetch("https://acme.example/old")
    assert result.ok
    assert result.final_url == "https://acme.example/new"
    assert result.metadata.get("redirected") is True


def test_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    client = httpx.Client(transport=_transport(handler), follow_redirects=True)
    with Fetcher(settings=_settings(), client=client, owns_client=True) as fetcher:
        result = fetcher.fetch("https://acme.example/")
    assert not result.ok
    assert result.error is not None
    assert "timeout" in result.error


def test_robots_disallow_blocks_fetch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nDisallow: /\n",
            )
        return httpx.Response(200, text=SAMPLE_HTML)

    client = httpx.Client(transport=_transport(handler), follow_redirects=True)
    with Fetcher(settings=_settings(), client=client, owns_client=True) as fetcher:
        result = fetcher.fetch("https://acme.example/")
    assert not result.ok
    assert result.blocked_by_robots


def test_changed_content_produces_new_hash() -> None:
    a = extract_content(SAMPLE_HTML, "https://acme.example/")
    b = extract_content(CHANGED_HTML, "https://acme.example/")
    assert a is not None and b is not None
    assert a.content_hash != b.content_hash
