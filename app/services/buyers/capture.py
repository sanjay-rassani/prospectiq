"""Capture named people from permitted public company pages only (spec §9.2)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Person, PersonSource, SourceSnapshot
from app.services.buyers.guardrails import (
    is_permitted_people_page,
    reject_guessed_email,
)
from app.services.buyers.role_map import all_known_roles

logger = logging.getLogger(__name__)

# "Jane Smith, Head of Operations" / "Jane Smith - CTO" / "Jane Smith | Founder"
_PERSON_LINE = re.compile(
    r"(?P<name>\b[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})"
    r"[ \t]*[,|\-\u2013\u2014:][ \t]*"
    r"(?P<role>[^\n.]{3,80})"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL = re.compile(r"https?://[^\s)>\"]+", re.IGNORECASE)


@dataclass(frozen=True)
class ExtractedPerson:
    name: str
    role: str
    public_email: str | None = None
    public_profile_url: str | None = None


def extract_people_from_text(text: str, *, company_domain: str) -> list[ExtractedPerson]:
    """Deterministic extraction. No LLM. No invented emails."""
    known = all_known_roles()
    known_needles = tuple(r.casefold() for r in known)
    emails_in_page = {m.group(0) for m in _EMAIL.finditer(text)}
    urls_in_page = [m.group(0).rstrip(".,;)") for m in _URL.finditer(text)]

    found: list[ExtractedPerson] = []
    seen: set[tuple[str, str]] = set()
    for match in _PERSON_LINE.finditer(text):
        name = match.group("name").strip()
        role_raw = match.group("role").strip()
        # Keep the role short; drop trailing clause noise.
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
            )
        )
        if not title_hit and not keyword_hit:
            continue
        key = (name.casefold(), role.casefold())
        if key in seen:
            continue
        seen.add(key)

        email = _nearest_email(text, match.start(), match.end(), emails_in_page)
        email = reject_guessed_email(name=name, domain=company_domain, email=email)
        profile = _nearest_profile_url(text, match.start(), match.end(), urls_in_page)

        found.append(
            ExtractedPerson(
                name=name[:255],
                role=role[:255],
                public_email=email,
                public_profile_url=profile,
            )
        )
    return found


def _nearest_email(
    text: str, start: int, end: int, emails: set[str]
) -> str | None:
    window = text[max(0, start - 120) : end + 120]
    for email in emails:
        if email in window:
            return email
    return None


def _nearest_profile_url(
    text: str, start: int, end: int, urls: list[str]
) -> str | None:
    window = text[max(0, start - 200) : end + 200]
    for url in urls:
        if url in window and "linkedin.com" in url.casefold():
            # A LinkedIn URL already published on the company page may be stored;
            # we still never fetch it (guardrails.assert_fetch_allowed).
            return url[:2048]
    return None


def capture_people_from_snapshots(
    session: Session,
    company: Company,
    snapshots: list[SourceSnapshot] | None = None,
) -> list[Person]:
    """Persist people found on permitted snapshots. Skips LinkedIn hosts entirely."""
    if snapshots is None:
        snapshots = list(
            session.scalars(
                select(SourceSnapshot).where(SourceSnapshot.company_id == company.id)
            ).all()
        )

    created: list[Person] = []
    existing = {
        (p.name.casefold(), p.role.casefold()): p
        for p in session.scalars(
            select(Person).where(Person.company_id == company.id)
        ).all()
    }

    for snap in snapshots:
        if not is_permitted_people_page(snap.url):
            continue
        for extracted in extract_people_from_text(snap.text, company_domain=company.domain):
            key = (extracted.name.casefold(), extracted.role.casefold())
            if key in existing:
                continue
            person = Person(
                company_id=company.id,
                name=extracted.name,
                role=extracted.role,
                public_email=extracted.public_email,
                public_profile_url=extracted.public_profile_url,
                source=PersonSource.COMPANY_PAGE.value,
                source_snapshot_id=snap.id,
            )
            session.add(person)
            existing[key] = person
            created.append(person)
            logger.info(
                "captured person %s (%s) from %s",
                person.name,
                person.role,
                snap.url,
            )
    session.flush()
    return created


def add_manual_person(
    session: Session,
    company: Company,
    *,
    name: str,
    role: str,
    public_email: str | None = None,
    public_profile_url: str | None = None,
) -> Person:
    """Operator-entered person. Emails are never invented; empty stays empty."""
    name = name.strip()
    role = role.strip()
    if not name or not role:
        raise ValueError("name and role are required")
    email = reject_guessed_email(
        name=name,
        domain=company.domain,
        email=(public_email or "").strip() or None,
    )
    # Operator may paste a LinkedIn profile URL — that is research, not scraping.
    profile = (public_profile_url or "").strip() or None
    person = Person(
        company_id=company.id,
        name=name[:255],
        role=role[:255],
        public_email=email,
        public_profile_url=profile[:2048] if profile else None,
        source=PersonSource.MANUAL.value,
    )
    session.add(person)
    session.flush()
    return person
