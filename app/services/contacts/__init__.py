"""Contact discovery, enrichment, and relevance ranking."""

from app.services.contacts.discover import (
    DiscoverContactsResult,
    add_manual_contact,
    delete_or_archive_contact,
    discover_contacts_for_company,
    enrich_person,
)
from app.services.contacts.extract import extract_people_from_text
from app.services.contacts.relevance import RankedContact, rank_contacts_for_opportunity

__all__ = [
    "DiscoverContactsResult",
    "RankedContact",
    "add_manual_contact",
    "delete_or_archive_contact",
    "discover_contacts_for_company",
    "enrich_person",
    "extract_people_from_text",
    "rank_contacts_for_opportunity",
]
