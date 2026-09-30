"""Treat fetched web text as hostile input (spec section 18, task P3-4).

Three layers, none of which assume the model cooperates:

1. Strip nulls and control characters that can confuse tokenisers.
2. Soften the most common "ignore previous instructions" patterns so they are visible
   as content rather than as directives, without deleting the evidence they contain.
3. Wrap the remainder in <source_text> markers and cap length so a huge page cannot
   crowd out the extraction instructions.
"""

from __future__ import annotations

import re

# Patterns that are almost never legitimate company copy and are classic injection bait.
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions?", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a|an|in)\b", re.I),
    re.compile(r"system\s*prompt\s*:", re.I),
    re.compile(r"</?\s*system\s*>", re.I),
)


def sanitize_fetched_text(text: str, *, max_chars: int) -> str:
    cleaned = text.replace("\x00", " ")
    cleaned = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub(lambda m: f"[quoted directive: {m.group(0)}]", cleaned)

    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rsplit(" ", 1)[0] + "\n…[truncated]"
    return cleaned
