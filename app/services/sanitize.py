"""XSS-safe rendering helpers for fetched content (P10-5)."""

from __future__ import annotations

import html
import re

# Strip tags that might sneak into extracted text before template render.
_TAG_RE = re.compile(r"<[^>]+>")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize_for_display(text: str | None, *, max_chars: int = 20000) -> str:
    """Escape HTML and strip residual tags/control chars from stored source text."""
    if not text:
        return ""
    cleaned = _CTRL_RE.sub("", text)
    cleaned = _TAG_RE.sub("", cleaned)
    cleaned = html.escape(cleaned, quote=True)
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "…"
    return cleaned
