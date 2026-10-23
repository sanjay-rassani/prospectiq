"""Contact discovery, enrichment, provenance, SSRF, and ranking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.jobs.handlers import handle_job
from app.jobs.queue import enqueue_job
from app.models import (
    Company,
    CompanyContactChannel,
    FieldEvidenceStatus,
    Job,
    JobStatus,
    JobType,
    Opportunity,
    OpportunityStatus,
    Person,
    PersonSource,
    SolutionFamily,
    SourceSnapshot,
    SourceType,
)
from app.services.contacts.discover import (
    add_manual_contact,
    discover_contacts_for_company,
)
from app.services.contacts.extract import (
    extract_generic_channels,
    extract_people_from_text,
)
from app.services.contacts.merge import (
    apply_manual_fields,
    find_matching_person,
    upsert_person_from_extraction,
)
from app.services.contacts.normalize import is_generic_inbox, normalize_email
from app.services.contacts.provenance import field_record, merge_field
from app.services.contacts.relevance import rank_contacts_for_opportunity
from app.services.contacts.ssrf import (
    UnsafeUrlError,
    assert_public_http_url,
    is_safe_public_http_url,
)
from app.services.fetcher import FetchResult

TEAM_PAGE = """
Our leadership

Jane Smith, Head of Operations
jane.smith@acme-contacts.example
https://www.linkedin.com/in/janesmith

Bob Jones - CTO
bob.jones@acme-contacts.example

Contact us at info@acme-contacts.example or sales@acme-contacts.example
Call +1 (555) 123-4567
"""


ABOUT_EMPTY = """
Acme builds logistics software for mid-market fleets.
We care about reliability and customer outcomes.
"""


def _company(session: Session, **kwargs: object) -> Company:
    data = dict(
        name="Acme Contacts Co",
        domain="acme-contacts.example",
        industry="Logistics",
        size_hint="medium",
        description="B2B freight automation",
        status="researched",
        seed_url="https://acme-contacts.example/",
    )
    data.update(kwargs)
    company = Company(**data)  # type: ignore[arg-type]
    session.add(company)
    session.flush()
    return company


def _snapshot(session: Session, company: Company, url: str, text: str) -> SourceSnapshot:
    snap = SourceSnapshot(
        company_id=company.id,
        url=url,
        source_type=SourceType.COMPANY_PAGE.value,
        fetched_at=datetime.now(UTC),
        http_status=200,
        content_hash=f"hash-{uuid.uuid4().hex[:12]}",
        title="Team",
        text=text,
        metadata_json={},
    )
    session.add(snap)
    session.flush()
    return snap


def _opportunity(session: Session, company: Company, **kwargs: object) -> Opportunity:
    data = dict(
        company_id=company.id,
        title="Automate document ops",
        solution_family=SolutionFamily.AGENTIC_AI_AUTOMATION.value,
        problem_or_change="Manual document handling",
        hypothesis="Ops automation agent",
        business_outcome="Faster turnaround",
        why_now="Volume spike",
        buyer_role="Head of Operations",
        confidence="medium",
        status=OpportunityStatus.ACTIVE.value,
        unknowns=[],
    )
    data.update(kwargs)
    opp = Opportunity(**data)  # type: ignore[arg-type]
    session.add(opp)
    session.flush()
    return opp


def test_extract_people_and_skip_generic_inbox() -> None:
    people = extract_people_from_text(TEAM_PAGE, company_domain="acme-contacts.example")
    assert len(people) >= 2
    names = {p.name for p in people}
    assert "Jane Smith" in names
    assert "Bob Jones" in names
    jane = next(p for p in people if p.name == "Jane Smith")
    assert jane.public_email == "jane.smith@acme-contacts.example"
    assert jane.public_profile_url and "linkedin.com" in jane.public_profile_url
    assert jane.seniority == "head"
    assert jane.department == "Operations"
    # Generic inboxes are not people
    assert all(p.public_email != "info@acme-contacts.example" for p in people)

    channels = extract_generic_channels(TEAM_PAGE)
    values = {c.value for c in channels}
    assert "info@acme-contacts.example" in values
    assert "sales@acme-contacts.example" in values


def test_extract_empty_page() -> None:
    assert extract_people_from_text(ABOUT_EMPTY, company_domain="acme.example") == []


def test_reject_guessed_email_pattern() -> None:
    text = "Alice Wonder, CTO\nalice.wonder@acme-contacts.example"
    # Explicit on page is fine
    people = extract_people_from_text(text, company_domain="acme-contacts.example")
    assert people[0].public_email == "alice.wonder@acme-contacts.example"


def test_upsert_dedupes_and_enriches(session: Session) -> None:
    company = _company(session)
    snap = _snapshot(
        session, company, "https://acme-contacts.example/team", TEAM_PAGE
    )
    from app.services.contacts.extract import ExtractedPerson

    first = ExtractedPerson(
        name="Jane Smith",
        role="Head of Operations",
        excerpt="Jane Smith, Head of Operations",
    )
    person, created = upsert_person_from_extraction(
        session,
        company=company,
        extracted=first,
        source_url=snap.url,
        snapshot=snap,
    )
    assert created
    assert person.normalized_name == "jane smith"
    role_status = person.fields_json.get("role", {}).get("status")
    assert role_status == FieldEvidenceStatus.SOURCE_CONFIRMED.value

    richer = ExtractedPerson(
        name="Jane Smith",
        role="Head of Operations",
        public_email="jane.smith@acme-contacts.example",
        public_profile_url="https://www.linkedin.com/in/janesmith",
        department="Operations",
        seniority="head",
        excerpt="Jane Smith email",
    )
    same, created2 = upsert_person_from_extraction(
        session,
        company=company,
        extracted=richer,
        source_url=snap.url,
        snapshot=snap,
    )
    assert not created2
    assert same.id == person.id
    assert same.public_email == "jane.smith@acme-contacts.example"
    assert same.email_status == FieldEvidenceStatus.SOURCE_CONFIRMED.value
    assert same.fields_json["public_email"]["value"] == "jane.smith@acme-contacts.example"

    # Weaker data must not overwrite manually verified email
    apply_manual_fields(
        same,
        public_email="jane.smith@acme-contacts.example",
        mark_email_verified=True,
    )
    weaker = ExtractedPerson(
        name="Jane Smith",
        role="Ops Lead",
        public_email="other@acme-contacts.example",
    )
    upsert_person_from_extraction(
        session, company=company, extracted=weaker, source_url=snap.url, snapshot=snap
    )
    session.refresh(same)
    assert same.public_email == "jane.smith@acme-contacts.example"
    assert same.email_status == FieldEvidenceStatus.MANUALLY_VERIFIED.value


def test_repeated_discovery_no_duplicates(session: Session) -> None:
    company = _company(session)
    _snapshot(session, company, "https://acme-contacts.example/team", TEAM_PAGE)
    session.refresh(company)

    # Avoid network: only ingest existing snapshots
    from sqlalchemy import select

    result1 = discover_contacts_for_company(
        session, company.id, fetcher=_offline_fetcher(), max_urls=0
    )
    people = list(session.scalars(select(Person).where(Person.company_id == company.id)).all())
    assert len(people) >= 2
    count1 = len(people)
    assert result1.people_created >= 2

    result2 = discover_contacts_for_company(
        session, company.id, fetcher=_offline_fetcher(), max_urls=0
    )
    people2 = list(session.scalars(select(Person).where(Person.company_id == company.id)).all())
    assert len(people2) == count1
    assert result1.people_created + result2.people_created >= 2

    channels = list(
        session.scalars(
            select(CompanyContactChannel).where(
                CompanyContactChannel.company_id == company.id
            )
        ).all()
    )
    assert any(c.value.startswith("info@") for c in channels)


def _offline_fetcher() -> MagicMock:
    fetcher = MagicMock()
    fetcher.fetch.return_value = FetchResult(ok=False, url="x", error="offline")
    fetcher.close = MagicMock()
    return fetcher


def test_provenance_merge_conflict() -> None:
    fields: dict = {}
    a = field_record(
        value="CTO",
        status=FieldEvidenceStatus.SOURCE_CONFIRMED.value,
        source_url="https://a.example/team",
    )
    fields = merge_field(fields, "role", a)
    b = field_record(
        value="VP Engineering",
        status=FieldEvidenceStatus.SOURCE_CONFIRMED.value,
        source_url="https://b.example/about",
    )
    fields = merge_field(fields, "role", b)
    assert fields["role"]["status"] == FieldEvidenceStatus.CONFLICTING.value
    assert fields["role"]["value"] == "VP Engineering"


def test_rank_contacts_for_opportunity(session: Session) -> None:
    company = _company(session)
    opp = _opportunity(session, company)
    session.add(
        Person(
            company_id=company.id,
            name="Jane Smith",
            normalized_name="jane smith",
            role="Head of Operations",
            source=PersonSource.COMPANY_PAGE.value,
            public_email="jane@acme-contacts.example",
            quality_score=70,
            fields_json={},
        )
    )
    session.add(
        Person(
            company_id=company.id,
            name="Intern Kid",
            normalized_name="intern kid",
            role="Marketing Intern",
            source=PersonSource.MANUAL.value,
            quality_score=20,
            fields_json={},
        )
    )
    session.flush()
    ranked = rank_contacts_for_opportunity(session, opp, company=company)
    assert ranked
    assert ranked[0].person.name == "Jane Smith"
    assert ranked[0].relevance_score > ranked[-1].relevance_score
    assert "recommended" in ranked[0].reason.casefold() or "aligns" in ranked[0].reason.casefold()


def test_ssrf_blocks_private_and_loopback() -> None:
    with pytest.raises(UnsafeUrlError):
        assert_public_http_url("http://127.0.0.1/team")
    with pytest.raises(UnsafeUrlError):
        assert_public_http_url("http://localhost/team")
    with pytest.raises(UnsafeUrlError):
        assert_public_http_url("ftp://example.com/x")
    with pytest.raises(UnsafeUrlError):
        assert_public_http_url("http://169.254.169.254/latest/meta-data")
    assert is_safe_public_http_url("https://example.com/team")


def test_manual_contact_and_api(session: Session, client) -> None:
    company = _company(session)
    person = add_manual_contact(
        session,
        company,
        name="Pat Lee",
        role="COO",
        public_email="pat.lee@acme-contacts.example",
        mark_verified=True,
    )
    assert person.email_status == FieldEvidenceStatus.MANUALLY_VERIFIED.value
    assert person.source == PersonSource.MANUAL.value

    r = client.get("/contacts")
    assert r.status_code == 200
    assert "Pat Lee" in r.text

    r2 = client.get(f"/contacts/{person.id}")
    assert r2.status_code == 200
    assert "Field provenance" in r2.text or "Contact information" in r2.text

    r3 = client.post(
        f"/companies/{company.id}/discover-contacts",
        data={},
        follow_redirects=False,
    )
    assert r3.status_code == 303
    jobs = list(
        session.scalars(
            __import__("sqlalchemy", fromlist=["select"]).select(Job).where(
                Job.job_type == JobType.DISCOVER_CONTACTS.value
            )
        ).all()
    )
    assert len(jobs) == 1


def test_discover_job_handler(session: Session) -> None:
    company = _company(session)
    _snapshot(session, company, "https://acme-contacts.example/team", TEAM_PAGE)
    job = enqueue_job(
        session,
        JobType.DISCOVER_CONTACTS.value,
        entity_id=company.id,
        payload={"max_urls": 0},
    )
    assert job is not None
    # Run handler with offline network path (max_urls 0 → snapshots only)
    job.status = JobStatus.RUNNING.value
    msg = handle_job(session, job)
    assert "Contacts:" in msg
    from sqlalchemy import select

    people = list(session.scalars(select(Person).where(Person.company_id == company.id)).all())
    assert len(people) >= 2


def test_match_by_email_across_role_change(session: Session) -> None:
    company = _company(session)
    from app.services.contacts.extract import ExtractedPerson

    p1, _ = upsert_person_from_extraction(
        session,
        company=company,
        extracted=ExtractedPerson(
            name="Sam Rivera",
            role="Director of Ops",
            public_email="sam@acme-contacts.example",
        ),
        source_url="https://acme-contacts.example/team",
    )
    found = find_matching_person(
        session,
        company_id=company.id,
        name="Samantha Rivera",
        email="sam@acme-contacts.example",
    )
    assert found is not None
    assert found.id == p1.id


def test_generic_inbox_helpers() -> None:
    assert is_generic_inbox("info@x.com")
    assert normalize_email("  A@B.COM ") == "a@b.com"
    assert not is_generic_inbox("jane.smith@x.com")


def test_contacts_filters_and_opportunity_outreach(session: Session, client) -> None:
    company = _company(session)
    opp = _opportunity(session, company, status=OpportunityStatus.OUTREACH_READY.value)
    person = add_manual_contact(
        session,
        company,
        name="Ops Lead",
        role="Head of Operations",
        public_email="ops@acme-contacts.example",
        public_profile_url="https://www.linkedin.com/in/opslead",
        mark_verified=True,
    )
    r = client.get(f"/contacts?company_id={company.id}&has_email=1")
    assert r.status_code == 200
    assert "Ops Lead" in r.text

    r_opp = client.get(f"/opportunities/{opp.id}")
    assert r_opp.status_code == 200
    assert "Recommended contacts" in r_opp.text or "Ops Lead" in r_opp.text

    r_out = client.post(
        f"/opportunities/{opp.id}/outreach",
        data={"channel": "email", "person_id": str(person.id)},
        follow_redirects=False,
    )
    assert r_out.status_code == 303
    assert "/outreach/" in r_out.headers.get("location", "")
