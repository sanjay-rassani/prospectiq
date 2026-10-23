"""Merge extracted contact evidence into Person rows with field-level provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company, SourceSnapshot
from app.models.person import (
    CompanyContactChannel,
    FieldEvidenceStatus,
    Person,
    PersonDiscoveryStatus,
    PersonSource,
)
from app.services.contacts.extract import ExtractedChannel, ExtractedPerson
from app.services.contacts.normalize import (
    is_generic_inbox,
    normalize_email,
    normalize_person_name,
    normalize_phone,
    person_match_key,
)
from app.services.contacts.provenance import field_record, merge_field


def find_matching_person(
    session: Session,
    *,
    company_id: UUID,
    name: str,
    email: str | None = None,
) -> Person | None:
    """Match by email within company, else by normalized name within company."""
    email_n = normalize_email(email)
    if email_n and not is_generic_inbox(email_n):
        existing = session.scalar(
            select(Person).where(
                Person.company_id == company_id,
                Person.public_email == email_n,
                Person.archived_at.is_(None),
            )
        )
        if existing:
            return existing

    nname = normalize_person_name(name)
    if nname:
        by_norm = session.scalar(
            select(Person).where(
                Person.company_id == company_id,
                Person.normalized_name == nname,
                Person.archived_at.is_(None),
            )
        )
        if by_norm:
            return by_norm

    key = person_match_key(name)
    people = session.scalars(
        select(Person).where(
            Person.company_id == company_id,
            Person.archived_at.is_(None),
        )
    ).all()
    for person in people:
        if person_match_key(person.name) == key:
            return person
    return None


def upsert_person_from_extraction(
    session: Session,
    *,
    company: Company,
    extracted: ExtractedPerson,
    source_url: str,
    snapshot: SourceSnapshot | None = None,
    source: str = PersonSource.COMPANY_PAGE.value,
) -> tuple[Person, bool]:
    """Create or enrich a Person. Returns (person, created)."""
    now = datetime.now(UTC)
    existing = find_matching_person(
        session,
        company_id=company.id,
        name=extracted.name,
        email=extracted.public_email,
    )
    if existing is None:
        fields: dict = {}
        for field, value, status in _initial_field_tuples(extracted, source_url, snapshot):
            rec = field_record(
                value=value,
                status=status,
                source_url=source_url,
                snapshot_id=snapshot.id if snapshot else None,
                excerpt=extracted.excerpt,
            )
            if rec:
                fields[field] = rec
        person = Person(
            company_id=company.id,
            name=extracted.name[:255],
            normalized_name=normalize_person_name(extracted.name),
            role=extracted.role[:255],
            department=extracted.department,
            seniority=extracted.seniority,
            public_email=normalize_email(extracted.public_email),
            public_phone=normalize_phone(extracted.public_phone),
            public_profile_url=extracted.public_profile_url,
            source=source,
            discovery_status=PersonDiscoveryStatus.DISCOVERED.value,
            email_status=(
                FieldEvidenceStatus.SOURCE_CONFIRMED.value
                if extracted.public_email
                else FieldEvidenceStatus.UNKNOWN.value
            ),
            profile_status=(
                FieldEvidenceStatus.SOURCE_CONFIRMED.value
                if extracted.public_profile_url
                else FieldEvidenceStatus.UNKNOWN.value
            ),
            last_researched_at=now,
            source_snapshot_id=snapshot.id if snapshot else None,
            fields_json=fields,
        )
        person.quality_score = float(_quality_score(person))
        session.add(person)
        session.flush()
        return person, True

    return _enrich_person(session, existing, extracted, source_url, snapshot), False


def _initial_field_tuples(
    extracted: ExtractedPerson,
    source_url: str,
    snapshot: SourceSnapshot | None,
) -> list[tuple[str, str | None, str]]:
    confirmed = FieldEvidenceStatus.SOURCE_CONFIRMED.value
    return [
        ("name", extracted.name, confirmed),
        ("role", extracted.role, confirmed),
        ("department", extracted.department, FieldEvidenceStatus.DISCOVERED.value),
        ("seniority", extracted.seniority, FieldEvidenceStatus.DISCOVERED.value),
        ("public_email", normalize_email(extracted.public_email), confirmed),
        ("public_phone", normalize_phone(extracted.public_phone), confirmed),
        ("public_profile_url", extracted.public_profile_url, confirmed),
    ]


def _enrich_person(
    session: Session,
    person: Person,
    extracted: ExtractedPerson,
    source_url: str,
    snapshot: SourceSnapshot | None,
) -> Person:
    fields = dict(person.fields_json or {})
    updates: list[tuple[str, str | None, str]] = [
        ("name", extracted.name, FieldEvidenceStatus.SOURCE_CONFIRMED.value),
        ("role", extracted.role, FieldEvidenceStatus.SOURCE_CONFIRMED.value),
        ("department", extracted.department, FieldEvidenceStatus.DISCOVERED.value),
        ("seniority", extracted.seniority, FieldEvidenceStatus.DISCOVERED.value),
        (
            "public_email",
            normalize_email(extracted.public_email),
            FieldEvidenceStatus.SOURCE_CONFIRMED.value,
        ),
        (
            "public_phone",
            normalize_phone(extracted.public_phone),
            FieldEvidenceStatus.SOURCE_CONFIRMED.value,
        ),
        (
            "public_profile_url",
            extracted.public_profile_url,
            FieldEvidenceStatus.SOURCE_CONFIRMED.value,
        ),
    ]
    changed = False
    for field, value, status in updates:
        if not value:
            continue
        # Never overwrite manually verified values with weaker observed data.
        current = fields.get(field) if isinstance(fields.get(field), dict) else None
        if (
            current
            and current.get("status") == FieldEvidenceStatus.MANUALLY_VERIFIED.value
        ):
            continue
        incoming = field_record(
            value=value,
            status=status,
            source_url=source_url,
            snapshot_id=snapshot.id if snapshot else None,
            excerpt=extracted.excerpt,
        )
        before = fields.get(field)
        fields = merge_field(fields, field, incoming)
        if fields.get(field) != before:
            changed = True
            setattr(person, field, value)
            if field == "name":
                person.normalized_name = normalize_person_name(value)
            if field == "public_email":
                person.email_status = FieldEvidenceStatus.SOURCE_CONFIRMED.value
            if field == "public_profile_url":
                person.profile_status = FieldEvidenceStatus.SOURCE_CONFIRMED.value

    person.fields_json = fields
    person.last_researched_at = datetime.now(UTC)
    if changed:
        person.discovery_status = PersonDiscoveryStatus.ENRICHED.value
    if snapshot and person.source_snapshot_id is None:
        person.source_snapshot_id = snapshot.id
    person.quality_score = float(_quality_score(person))
    session.add(person)
    session.flush()
    return person


def upsert_company_channel(
    session: Session,
    *,
    company: Company,
    channel: ExtractedChannel,
    source_url: str | None,
    snapshot: SourceSnapshot | None = None,
) -> tuple[CompanyContactChannel | None, bool]:
    """Returns (row, created)."""
    if channel.channel_type == "email" and not is_generic_inbox(channel.value):
        return None, False
    existing = session.scalar(
        select(CompanyContactChannel).where(
            CompanyContactChannel.company_id == company.id,
            CompanyContactChannel.channel_type == channel.channel_type,
            CompanyContactChannel.value == channel.value,
        )
    )
    if existing:
        return existing, False
    row = CompanyContactChannel(
        company_id=company.id,
        channel_type=channel.channel_type,
        value=channel.value[:320],
        label=(channel.label or "")[:64] or None,
        source_url=source_url,
        source_snapshot_id=snapshot.id if snapshot else None,
        is_generic=True,
    )
    session.add(row)
    session.flush()
    return row, True


def apply_manual_fields(
    person: Person,
    *,
    name: str | None = None,
    role: str | None = None,
    department: str | None = None,
    seniority: str | None = None,
    public_email: str | None = None,
    public_phone: str | None = None,
    public_profile_url: str | None = None,
    notes: str | None = None,
    mark_email_verified: bool = False,
    mark_profile_verified: bool = False,
) -> Person:
    """Operator edit path — provenance confidence becomes manually_verified."""
    fields = dict(person.fields_json or {})
    mapping: dict[str, str | None] = {
        "name": name,
        "role": role,
        "department": department,
        "seniority": seniority,
        "public_email": normalize_email(public_email) if public_email is not None else None,
        "public_phone": normalize_phone(public_phone) if public_phone is not None else None,
        "public_profile_url": public_profile_url,
    }
    for field, value in mapping.items():
        if value is None:
            continue
        if value == "":
            setattr(person, field, None)
            continue
        rec = field_record(
            value=value,
            status=FieldEvidenceStatus.MANUALLY_VERIFIED.value,
            source_url="manual",
            excerpt=None,
        )
        fields = merge_field(fields, field, rec)
        setattr(person, field, value)
        if field == "name":
            person.normalized_name = normalize_person_name(value)

    if mark_email_verified and person.public_email:
        person.email_status = FieldEvidenceStatus.MANUALLY_VERIFIED.value
        person.verified_at = datetime.now(UTC)
    if mark_profile_verified and person.public_profile_url:
        person.profile_status = FieldEvidenceStatus.MANUALLY_VERIFIED.value
        person.verified_at = datetime.now(UTC)
    if notes is not None:
        person.notes = notes[:4000]
    person.fields_json = fields
    person.quality_score = float(_quality_score(person))
    person.source = person.source or PersonSource.MANUAL.value
    if person.source == PersonSource.COMPANY_PAGE.value and any(
        mapping.get(k) for k in ("public_email", "public_profile_url", "name", "role")
    ):
        # Keep original discovery source; manual edits only bump provenance.
        pass
    return person


def archive_person(person: Person) -> None:
    person.archived_at = datetime.now(UTC)
    person.discovery_status = PersonDiscoveryStatus.ARCHIVED.value


def _quality_score(person: Person) -> int:
    score = 20
    if person.role:
        score += 15
    if person.public_email:
        score += 25
        if person.email_status == FieldEvidenceStatus.MANUALLY_VERIFIED.value:
            score += 10
        elif person.email_status == FieldEvidenceStatus.SOURCE_CONFIRMED.value:
            score += 5
    if person.public_profile_url:
        score += 15
    if person.public_phone:
        score += 5
    if person.department:
        score += 5
    if person.verified_at is not None:
        score += 10
    return min(100, score)
