"""Verbatim evidence checks (spec section 6.2, task P4-2).

A signal whose evidence_excerpt is not present in the source is fabricated proof and must
never be persisted. Cosmetic quote/dash differences are forgiven; paraphrase is not.
"""

from __future__ import annotations

import re
import unicodedata

_TRANSLATIONS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
        "\u2026": "...",
    }
)


def normalize_evidence_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATIONS)
    return re.sub(r"\s+", " ", text).strip().casefold()


def evidence_is_verbatim(excerpt: str, source_text: str) -> bool:
    needle = normalize_evidence_text(excerpt)
    if not needle or len(needle) < 8:
        return False
    return needle in normalize_evidence_text(source_text)
