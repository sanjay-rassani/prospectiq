"""Unit tests for domain normalization (FR-02)."""

import pytest

from app.services.discovery.normalize import (
    canonicalize_url,
    normalize_domain,
    parse_seed_blob,
    parse_seed_line,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", "example.com"),
        ("EXAMPLE.COM", "example.com"),
        ("www.example.com", "example.com"),
        ("https://www.example.com/", "example.com"),
        ("https://example.com/about?x=1", "example.com"),
        ("http://blog.example.com/post", "blog.example.com"),
        ("Acme | www.example.com", "example.com"),
        ("example.com.", "example.com"),
    ],
)
def test_normalize_domain(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "not a domain", "localhost", "http://127.0.0.1/", "foo", "http://"],
)
def test_normalize_domain_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_domain(raw)


def test_canonicalize_url_strips_www_and_trailing_slash() -> None:
    assert canonicalize_url("https://www.example.com/about/") == "https://example.com/about"
    assert canonicalize_url("example.com") == "https://example.com/"


def test_parse_seed_line_with_name() -> None:
    target = parse_seed_line("Acme Corp | https://www.acme.io/about")
    assert target.domain == "acme.io"
    assert target.url == "https://acme.io/about"
    assert target.name_hint == "Acme Corp"


def test_parse_seed_blob_dedupes_by_domain() -> None:
    blob = """
    # comment
    example.com
    https://www.example.com/about
    Other | other.io
    """
    targets = parse_seed_blob(blob)
    assert [t.domain for t in targets] == ["example.com", "other.io"]
    # First occurrence wins for URL.
    assert targets[0].url == "https://example.com/"
