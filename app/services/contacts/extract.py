"""Deterministic contact extraction from permitted page text (no LLM, no guessing)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.buyers.role_map import all_known_roles
from app.services.contacts.normalize import (
    extract_phones,
    is_generic_inbox,
    normalize_email,
    normalize_phone,
)

# "Jane Smith, Head of Operations" / "Jane Smith - CTO" / "Jane Smith | Founder"
_PERSON_LINE = re.compile(
    r"(?P<name>\b[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})"
    r"[ \t]*[,|\-\u2013\u2014:][ \t]*"
    r"(?P<role>[^\n.]{3,80})"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_MAILTO = re.compile(
    r"mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", re.I
)
_URL = re.compile(r"https?://[^\s)>\"]+", re.IGNORECASE)

_SENIORITY_HINTS = (
    ("ceo", "c-level"),
    ("cto", "c-level"),
    ("coo", "c-level"),
    ("cfo", "c-level"),
    ("founder", "founder"),
    ("president", "executive"),
    ("vp ", "vp"),
    ("vice president", "vp"),
    ("head of", "head"),
    ("director", "director"),
    ("manager", "manager"),
    ("lead", "lead"),
)

_DEPT_HINTS = (
    ("operations", "Operations"),
    ("engineering", "Engineering"),
    ("product", "Product"),
    ("sales", "Sales"),
    ("marketing", "Marketing"),
    ("finance", "Finance"),
    ("people", "People"),
    ("hr", "People"),
    ("it ", "IT"),
    ("technology", "Technology"),
    ("data", "Data"),
)


@dataclass(frozen=True)
class ExtractedPerson:
    name: str
    role: str
    public_email: str | None = None
    public_profile_url: str | None = None
    public_phone: str | None = None
    department: str | None = None
    seniority: str | None = None
    excerpt: str | None = None


@dataclass(frozen=True)
class ExtractedChannel:
    channel_type: str
    value: str
    label: str | None = None


def infer_seniority(role: str) -> str | None:
    role_cf = role.casefold()
    for needle, label in _SENIORITY_HINTS:
        if needle in role_cf:
            return label
    return None


def infer_department(role: str) -> str | None:
    role_cf = role.casefold()
    for needle, label in _DEPT_HINTS:
        if needle in role_cf:
            return label
    return None


def extract_people_from_text(text: str, *, company_domain: str) -> list[ExtractedPerson]:
    """Deterministic extraction. No LLM. No invented emails."""
    known = all_known_roles()
    known_needles = tuple(r.casefold() for r in known)
    emails_in_page = {m.group(0) for m in _EMAIL.finditer(text or "")}
    emails_in_page.update(m.group(1) for m in _MAILTO.finditer(text or ""))
    urls_in_page = [m.group(0).rstrip(".,;)") for m in _URL.finditer(text or "")]
    phones = extract_phones(text or "")

    found: list[ExtractedPerson] = []
    seen: set[tuple[str, str]] = set()
    for match in _PERSON_LINE.finditer(text or ""):
        name = match.group("name").strip()
        role_raw = match.group("role").strip()
        role = re.split(r"[.(]", role_raw, maxsplit=1)[0].strip()
        if len(role) < 3 or len(role) > 80:
            continue
        role_cf = role.casefold()
        title_hit = any(needle in role_cf or role_cf in needle for needle in known_needles)
        keyword_hit = any(
            token in role_cf
            for token in (
                "ceo",
                "cto",
                "coo",
                "cpo",
                "founder",
                "director",
                "head of",
                "vp ",
                "vice president",
                "owner",
                "lead",
                "manager",
            )
        )
        if not title_hit and not keyword_hit:
            continue
        key = (name.casefold(), role.casefold())
        if key in seen:
            continue
        seen.add(key)

        # Email must already appear on the page near the person — never invented.
        # Name-shaped locals (jane.smith@) are allowed when literally published.
        email = normalize_email(
            _nearest_email(text, match.start(), match.end(), emails_in_page)
        )
        if email and is_generic_inbox(email):
            email = None

        profile = _nearest_profile_url(text, match.start(), match.end(), urls_in_page)
        phone = _nearest_phone(text, match.start(), match.end(), phones)
        excerpt = (text or "")[max(0, match.start() - 40) : match.end() + 40].strip()

        found.append(
            ExtractedPerson(
                name=name[:255],
                role=role[:255],
                public_email=email,
                public_profile_url=profile,
                public_phone=phone,
                department=infer_department(role),
                seniority=infer_seniority(role),
                excerpt=excerpt[:400] if excerpt else None,
            )
        )
    return found


def extract_generic_channels(text: str) -> list[ExtractedChannel]:
    channels: list[ExtractedChannel] = []
    seen: set[str] = set()
    for match in _EMAIL.finditer(text or ""):
        email = normalize_email(match.group(0))
        if not email or email in seen:
            continue
        if not is_generic_inbox(email):
            continue
        seen.add(email)
        local = email.split("@", 1)[0]
        channels.append(ExtractedChannel(channel_type="email", value=email, label=local))
    for phone in extract_phones(text or ""):
        if phone in seen:
            continue
        seen.add(phone)
        channels.append(ExtractedChannel(channel_type="phone", value=phone, label="phone"))
    return channels


def _nearest_email(text: str, start: int, end: int, emails: set[str]) -> str | None:
    """Pick the non-generic email whose first occurrence is closest to the name span."""
    mid = (start + end) // 2
    best: str | None = None
    best_dist = 10**9
    # Prefer emails after the name (typical "Name, Role\nemail") within a tight window.
    search_from = max(0, start - 40)
    search_to = min(len(text), end + 120)
    region = text[search_from:search_to]
    for email in emails:
        if is_generic_inbox(email):
            continue
        pos = region.find(email)
        if pos < 0:
            continue
        abs_pos = search_from + pos
        dist = abs(abs_pos - mid)
        if dist < best_dist:
            best_dist = dist
            best = email
    return best


def _nearest_phone(text: str, start: int, end: int, phones: list[str]) -> str | None:
    mid = (start + end) // 2
    best: str | None = None
    best_dist = 10**9
    search_from = max(0, start - 40)
    search_to = min(len(text), end + 120)
    region = text[search_from:search_to]
    region_digits = re.sub(r"\D", "", region)
    for phone in phones:
        digits = re.sub(r"\D", "", phone)
        if phone in region or (digits and digits in region_digits):
            pos = region.find(phone) if phone in region else 0
            dist = abs((search_from + max(pos, 0)) - mid)
            if dist < best_dist:
                best_dist = dist
                best = phone
    return normalize_phone(best)


def _nearest_profile_url(text: str, start: int, end: int, urls: list[str]) -> str | None:
    mid = (start + end) // 2
    best: str | None = None
    best_dist = 10**9
    search_from = max(0, start - 40)
    search_to = min(len(text), end + 160)
    region = text[search_from:search_to]
    for url in urls:
        if "linkedin.com" not in url.casefold():
            continue
        pos = region.find(url)
        if pos < 0:
            continue
        dist = abs((search_from + pos) - mid)
        if dist < best_dist:
            best_dist = dist
            best = url
    return best[:2048] if best else None
