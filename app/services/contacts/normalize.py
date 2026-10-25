"""Normalize contact names, emails, phones, and URLs."""

from __future__ import annotations

import re


def normalize_person_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", (name or "").strip().casefold())
    return " ".join(cleaned.split())


# Alias used by merge/discover.
normalize_name = normalize_person_name


def person_match_key(name: str) -> str:
    return normalize_person_name(name)


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    cleaned = email.strip().casefold()
    if "@" not in cleaned or "." not in cleaned.split("@", 1)[-1]:
        return None
    if any(ch.isspace() for ch in cleaned):
        return None
    return cleaned


_PHONE = re.compile(r"(?:\+|00)?[\d][\d\s().\-]{7,18}\d")


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d+]", "", raw.strip())
    if len(re.sub(r"\D", "", digits)) < 8:
        return None
    return digits[:64]


def extract_phones(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _PHONE.finditer(text or ""):
        phone = normalize_phone(match.group(0))
        if phone and phone not in seen:
            seen.add(phone)
            found.append(phone)
    return found


GENERIC_LOCAL_PARTS = frozenset(
    {
        "info",
        "support",
        "sales",
        "hello",
        "contact",
        "admin",
        "marketing",
        "press",
        "media",
        "team",
        "office",
        "enquiries",
        "inquiry",
        "help",
        "noreply",
        "no-reply",
        "donotreply",
    }
)


def email_local_part(email: str) -> str:
    return email.split("@", 1)[0].casefold()


def is_generic_inbox(email: str) -> bool:
    local = email_local_part(email)
    return local in GENERIC_LOCAL_PARTS or local.startswith("noreply")
