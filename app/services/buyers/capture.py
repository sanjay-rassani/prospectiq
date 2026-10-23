"""Capture named people from permitted public company pages only (spec §9.2).

Delegates extraction/merge to app.services.contacts so enrichment and provenance
stay in one place.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Person, SourceSnapshot
from app.services.buyers.guardrails import is_permitted_people_page
from app.services.contacts.discover import add_manual_contact
from app.services.contacts.extract import ExtractedPerson, extract_people_from_text
from app.services.contacts.merge import upsert_person_from_extraction

logger = logging.getLogger(__name__)

__all__ = [
    "ExtractedPerson",
    "add_manual_person",
    "capture_people_from_snapshots",
    "extract_people_from_text",
]


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
    for snap in snapshots:
        if not is_permitted_people_page(snap.url):
            continue
        for extracted in extract_people_from_text(snap.text, company_domain=company.domain):
            person, was_created = upsert_person_from_extraction(
                session,
                company=company,
                extracted=extracted,
                source_url=snap.url,
                snapshot=snap,
            )
            if was_created:
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
    return add_manual_contact(
        session,
        company,
        name=name,
        role=role,
        public_email=public_email,
        public_profile_url=public_profile_url,
        mark_verified=True,
    )
