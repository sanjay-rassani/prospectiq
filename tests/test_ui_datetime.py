"""UI datetime display: Pakistan primary, US Eastern in brackets."""

from __future__ import annotations

from datetime import UTC, datetime

from app.ui.datetime_display import format_when, when_badge


def test_format_when_pakistan_and_us() -> None:
    # 2026-10-23 06:40 UTC → 11:40 AM PKT, 2:40 AM EDT
    value = datetime(2026, 10, 23, 6, 40, tzinfo=UTC)
    text = format_when(value)
    assert "PKT" in text
    assert "(" in text and ")" in text
    assert "11:40 AM PKT" in text
    assert "2:40 AM" in text


def test_format_when_none() -> None:
    assert format_when(None) == "—"


def test_when_badge_html() -> None:
    value = datetime(2026, 10, 23, 6, 40, tzinfo=UTC)
    html = str(when_badge(value))
    assert "<time" in html
    assert "PKT" in html
    assert "title=" in html
