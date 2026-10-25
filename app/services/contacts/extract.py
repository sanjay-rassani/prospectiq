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

_NAME = r"(?P<name>\b[A-Z][a-z]+(?:[ \t]+[A-Z][a-z'\-]+){1,3})"

# "Jane Smith, Head of Operations" / "Jane Smith - CTO" / "Jane Smith | Founder"
_PERSON_LINE = re.compile(
    _NAME
    + r"[ \t]*[,|\-\u2013\u2014:][ \t]*"
    + r"(?P<role>[^\n.]{3,80})"
)
# "Jane Smith (CEO)" / "Jane Smith (Head of Product)"
_PERSON_PAREN = re.compile(
    _NAME + r"[ \t]*\((?P<role>[^)\n]{2,60})\)"
)
# "CEO: Jane Smith" / "Founder — Jane Smith"
_ROLE_THEN_NAME = re.compile(
    r"(?P<role>\b(?:CEO|CTO|COO|CFO|CPO|CMO|Founder|Co-Founder|President|"
    r"Managing Director|Director|Head of [A-Za-z &/]+|VP(?: of)?[A-Za-z &/]*|"
    r"Vice President(?: of)?[A-Za-z &/]*|Owner|Partner)\b)"
    r"[ \t]*[:|\-\u2013\u2014][ \t]*"
    + _NAME,
    re.IGNORECASE,
)
# Two-line blocks: "Jane Smith\nHead of Operations"
_TWO_LINE = re.compile(
    _NAME + r"\n[ \t]*(?P<role>[A-Za-z][^\n]{2,70})"
)
# mailto:jane@x with nearby capitalized name
_MAILTO_NEAR_NAME = re.compile(
    _NAME
    + r".{0,80}?"
    + r"(?:mailto:)?(?P<email>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
    re.IGNORECASE | re.DOTALL,
)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_MAILTO = re.compile(
    r"mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", re.I
)
_URL = re.compile(r"https?://[^\s)>\"]+", re.IGNORECASE)

_ROLE_KEYWORDS = (
    "ceo",
    "cto",
    "coo",
    "cfo",
    "cpo",
    "cmo",
    "founder",
    "co-founder",
    "director",
    "head of",
    "vp ",
    "vice president",
    "owner",
    "partner",
    "lead",
    "manager",
    "president",
    "principal",
    "chief ",
)

_SENIORITY_HINTS = (
    ("ceo", "c-level"),
    ("cto", "c-level"),
    ("coo", "c-level"),
    ("cfo", "c-level"),
    ("cpo", "c-level"),
    ("cmo", "c-level"),
    ("founder", "founder"),
    ("president", "executive"),
    ("vp ", "vp"),
    ("vice president", "vp"),
    ("head of", "head"),
    ("director", "director"),
    ("manager", "manager"),
    ("lead", "lead"),
    ("partner", "partner"),
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
    body = text or ""
    emails_in_page = {m.group(0) for m in _EMAIL.finditer(body)}
    emails_in_page.update(m.group(1) for m in _MAILTO.finditer(body))
    urls_in_page = [m.group(0).rstrip(".,;)") for m in _URL.finditer(body)]
    phones = extract_phones(body)

    found: list[ExtractedPerson] = []
    seen: set[tuple[str, str]] = set()

    def role_ok(role: str) -> bool:
        role_cf = role.casefold()
        if any(needle in role_cf or role_cf in needle for needle in known_needles):
            return True
        return any(token in role_cf for token in _ROLE_KEYWORDS)

    def add(
        *,
        name: str,
        role: str,
        start: int,
        end: int,
        email_hint: str | None = None,
        require_role_title: bool = True,
    ) -> None:
        name = name.strip()
        role = re.split(r"[.(|/]", role.strip(), maxsplit=1)[0].strip()
        role = re.sub(r"\s+", " ", role)
        if len(name) < 3 or len(role) < 2 or len(role) > 80:
            return
        if require_role_title and not role_ok(role):
            return
        # Skip junk roles that are just conjunctions / UI chrome.
        if role.casefold() in {"and", "or", "the", "with", "from", "email", "phone"}:
            return
        key = (name.casefold(), role.casefold())
        if key in seen:
            return
        # Skip duplicate name when we already captured them with a real title.
        name_only = name.casefold()
        if any(n == name_only for n, _ in seen) and not require_role_title:
            return
        seen.add(key)

        email = normalize_email(email_hint) if email_hint else None
        if not email:
            email = normalize_email(_nearest_email(body, start, end, emails_in_page))
        if email and is_generic_inbox(email):
            email = None
        # Prefer emails on the company domain when several are nearby.
        if email and company_domain and "@" in email:
            host = email.split("@", 1)[1].casefold()
            if company_domain.casefold() not in host and host not in company_domain.casefold():
                # Keep non-company emails that were literally published (contractors, etc.)
                pass

        profile = _nearest_profile_url(body, start, end, urls_in_page)
        phone = _nearest_phone(body, start, end, phones)
        excerpt = body[max(0, start - 40) : end + 40].strip()
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

    for match in _PERSON_LINE.finditer(body):
        add(
            name=match.group("name"),
            role=match.group("role"),
            start=match.start(),
            end=match.end(),
        )
    for match in _PERSON_PAREN.finditer(body):
        add(
            name=match.group("name"),
            role=match.group("role"),
            start=match.start(),
            end=match.end(),
        )
    for match in _ROLE_THEN_NAME.finditer(body):
        add(
            name=match.group("name"),
            role=match.group("role"),
            start=match.start(),
            end=match.end(),
        )
    for match in _TWO_LINE.finditer(body):
        add(
            name=match.group("name"),
            role=match.group("role"),
            start=match.start(),
            end=match.end(),
        )
    for match in _MAILTO_NEAR_NAME.finditer(body):
        email = normalize_email(match.group("email"))
        if not email or is_generic_inbox(email):
            continue
        # Published personal email next to a name — keep even without a title.
        add(
            name=match.group("name"),
            role="Published contact",
            start=match.start(),
            end=match.end(),
            email_hint=email,
            require_role_title=False,
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
    search_from = max(0, start - 60)
    search_to = min(len(text), end + 160)
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
