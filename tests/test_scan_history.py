"""Friendly contact-scan history lines."""

from __future__ import annotations

from app.services.contacts.scan_history import humanize_scan_error


def test_humanize_multi_404() -> None:
    raw = (
        "RuntimeError: https://globus.software/about: HTTP 404; "
        "https://globus.software/about-us: HTTP 404; "
        "https://globus.software/team: HTTP 404"
    )
    text = humanize_scan_error(raw)
    assert "RuntimeError" not in text
    assert "HTTP 404" not in text
    assert "missing" in text.casefold() or "not found" in text.casefold()
    assert "://" not in text


def test_humanize_robots() -> None:
    assert "robots" in humanize_scan_error("https://x.com/team: blocked by robots.txt").casefold()
