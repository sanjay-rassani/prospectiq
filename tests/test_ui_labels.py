"""Friendly status labels and hover badges."""

from __future__ import annotations

from app.ui.labels import lookup_term, priority_badge, status_badge, status_label


def test_outreach_ready_is_plain_english() -> None:
    assert status_label("outreach_ready", "opportunity") == "Ready to approach"
    term = lookup_term("outreach_ready", "opportunity")
    assert "send" in term.help.casefold()


def test_draft_ready_badge_has_tooltip() -> None:
    html = str(status_badge("draft_ready", "outreach"))
    assert "Draft ready for you" in html
    assert 'title="' in html
    assert "term" in html


def test_priority_badge_keeps_band_class() -> None:
    html = str(priority_badge("high"))
    assert "band-high" in html
    assert "High" in html


def test_unknown_code_prettifies() -> None:
    assert status_label("some_new_thing", "opportunity") == "Some new thing"
