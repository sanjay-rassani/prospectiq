"""Format datetimes for the UI: Pakistan time primary, US Eastern in brackets."""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from zoneinfo import ZoneInfo

from markupsafe import Markup

PK_TZ = ZoneInfo("Asia/Karachi")
US_TZ = ZoneInfo("America/New_York")

_EMPTY = "—"


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _ampm(dt: datetime) -> str:
    hour12 = dt.hour % 12 or 12
    meridiem = "AM" if dt.hour < 12 else "PM"
    return f"{hour12}:{dt.minute:02d} {meridiem}"


def format_when(value: datetime | None, *, empty: str = _EMPTY) -> str:
    """Plain text: ``23 Oct 2026, 1:22 PM PKT (5:22 AM EDT)``."""
    if value is None:
        return empty
    if not isinstance(value, datetime):
        return str(value)

    aware = _as_aware(value)
    pk = aware.astimezone(PK_TZ)
    us = aware.astimezone(US_TZ)
    us_abbr = us.tzname() or "ET"
    pk_part = f"{pk.strftime('%d %b %Y')}, {_ampm(pk)} PKT"
    us_part = f"{_ampm(us)} {us_abbr}"
    return f"{pk_part} ({us_part})"


def when_badge(value: datetime | None, *, empty: str = _EMPTY) -> Markup:
    """HTML ``<time>`` with Pakistan primary and US Eastern in brackets."""
    if value is None:
        return Markup(escape(empty))
    if not isinstance(value, datetime):
        return Markup(escape(str(value)))

    text = format_when(value, empty=empty)
    aware = _as_aware(value)
    utc_iso = aware.astimezone(UTC).isoformat()
    title = (
        f"Pakistan (Asia/Karachi): {aware.astimezone(PK_TZ).strftime('%d %b %Y, %H:%M')} · "
        f"US Eastern: {aware.astimezone(US_TZ).strftime('%d %b %Y, %H:%M %Z')} · "
        f"Stored UTC: {utc_iso}"
    )
    return Markup(
        f'<time class="when" datetime="{escape(utc_iso)}" title="{escape(title)}">'
        f"{escape(text)}</time>"
    )
