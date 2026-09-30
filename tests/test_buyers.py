"""Phase 6: buyer roles, person capture, research tasks, guardrails."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    Opportunity,
    OpportunityStatus,
    Person,
    PersonSource,
    ResearchTask,
    ResearchTaskStatus,
    SolutionFamily,
    SourceSnapshot,
    SourceType,
)
from app.services.buyers.capture import (
    add_manual_person,
    capture_people_from_snapshots,
    extract_people_from_text,
)
from app.services.buyers.guardrails import (
    BuyerGuardrailError,
    assert_fetch_allowed,
    is_permitted_people_page,
    reject_guessed_email,
)
from app.services.buyers.recommend import (
    apply_buyer_role,
    recommend_buyer_role_deterministic,
)
from app.services.buyers.research_tasks import ensure_research_task, research_task_title
from app.services.buyers.role_map import normalize_to_vocabulary, roles_for_family
from app.services.buyers.service import process_buyers_for_company
from app.services.llm.gateway import CallResult
from app.services.llm.schemas import BuyerRoleRecommendation


def _company(**kwargs: object) -> Company:
    data = dict(
        name="Acme Logistics",
        domain="acme-buyers.example",
        industry="Logistics",
        size_hint="medium",
        description="B2B freight",
        status="researched",
    )
    data.update(kwargs)
    return Company(**data)  # type: ignore[arg-type]


def _opportunity(company: Company, **kwargs: object) -> Opportunity:
    data = dict(
        company_id=company.id,
        title="Automate depot reconciliation",
        solution_family=SolutionFamily.AGENTIC_AI_AUTOMATION.value,
        problem_or_change="Manual spreadsheet reconciliation",
        hypothesis="Build an ops automation agent",
        business_outcome="Fewer evening reconciliations",
        why_now="Third depot opened",
        buyer_role="Operations Director",
        confidence="medium",
        status=OpportunityStatus.ACTIVE.value,
        unknowns=[],
    )
    data.update(kwargs)
    return Opportunity(**data)  # type: ignore[arg-type]


def test_role_map_matches_spec_families() -> None:
    roles = roles_for_family(SolutionFamily.MODERNIZATION_SCALE.value)
    assert "CTO" in roles
    assert "VP Engineering" in roles
    agency = roles_for_family(
        SolutionFamily.CUSTOM_SOFTWARE_SAAS.value,
        industry="Digital agency",
        description="White-label product studio",
        name="North Agency",
    )
    assert agency[0] in {"Founder", "Agency Owner", "Delivery/Technology Director"}


def test_normalize_maps_freeform_to_vocabulary() -> None:
    allowed = roles_for_family(SolutionFamily.AGENTIC_AI_AUTOMATION.value)
    assert normalize_to_vocabulary("Head of Ops", allowed) == "Head of Operations"
    assert normalize_to_vocabulary("Operations Director", allowed) == "Operations Director"
    assert normalize_to_vocabulary("Wizard of Oz", allowed) is None


def test_deterministic_recommend_aligns_and_defaults() -> None:
    import uuid

    company = _company(size_hint="small")
    opp = Opportunity(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        title="Portal",
        solution_family=SolutionFamily.CUSTOM_SOFTWARE_SAAS.value,
        problem_or_change="x",
        hypothesis="y",
        business_outcome="z",
        why_now="now",
        buyer_role="product lead",
        confidence="low",
        status="active",
        unknowns=[],
    )
    rec = recommend_buyer_role_deterministic(opp, company)
    assert rec.role in roles_for_family(SolutionFamily.CUSTOM_SOFTWARE_SAAS.value)
    assert "Founder" in rec.role or rec.role == "CPO/Product Lead" or rec.role == "CTO"


def test_llm_out_of_vocab_falls_back(session: Session) -> None:
    company = _company()
    session.add(company)
    session.flush()
    opp = _opportunity(company, buyer_role="Someone Weird")
    session.add(opp)
    session.flush()

    class BadGateway:
        def recommend_buyer_role(self, *, opportunity_json: str) -> CallResult:
            parsed = BuyerRoleRecommendation(role="Marketing Intern", rationale="nope")
            return CallResult(
                ok=True,
                parsed=parsed,
                raw_output=parsed.model_dump_json(),
                model="fake",
                prompt_version="v1",
                task="recommend_buyer_role",
                seconds=0.01,
                attempts=1,
            )

        def extract_facts(self, *, url: str, text: str) -> CallResult:
            raise NotImplementedError

        def extract_signals(self, *, url: str, text: str) -> CallResult:
            raise NotImplementedError

        def generate_opportunities(
            self, *, facts_json: str, signals_json: str
        ) -> CallResult:
            raise NotImplementedError

    from app.services.buyers.recommend import recommend_buyer_role

    rec = recommend_buyer_role(opp, company, gateway=BadGateway(), session=session)
    assert rec.role in roles_for_family(opp.solution_family)
    assert rec.role != "Marketing Intern"


def test_guardrails_block_linkedin_fetch_and_guessed_email() -> None:
    assert is_permitted_people_page("https://acme.example/about/team")
    assert not is_permitted_people_page("https://acme.example/")
    assert not is_permitted_people_page("https://www.linkedin.com/in/jane")
    try:
        assert_fetch_allowed("https://linkedin.com/in/jane")
        raise AssertionError("expected BuyerGuardrailError")
    except BuyerGuardrailError:
        pass
    assert (
        reject_guessed_email(
            name="Jane Smith", domain="acme.example", email="jane.smith@acme.example"
        )
        is None
    )
    assert (
        reject_guessed_email(
            name="Jane Smith",
            domain="acme.example",
            email="jane@othermail.com",
        )
        == "jane@othermail.com"
    )


def test_extract_people_from_team_page_text() -> None:
    text = (
        "Leadership\n"
        "Jane Smith, Head of Operations\n"
        "Contact jane.ops@acme.example for partnerships.\n"
        "Alex Brown — CTO\n"
    )
    people = extract_people_from_text(text, company_domain="acme.example")
    names = {p.name for p in people}
    assert "Jane Smith" in names
    assert "Alex Brown" in names
    jane = next(p for p in people if p.name == "Jane Smith")
    # jane.ops is not a guessed first.last pattern against domain — allow if present
    assert jane.role == "Head of Operations"


def test_capture_only_from_permitted_snapshots(session: Session) -> None:
    company = _company()
    session.add(company)
    session.flush()
    home = SourceSnapshot(
        company_id=company.id,
        url="https://acme-buyers.example/",
        source_type=SourceType.COMPANY_PAGE.value,
        fetched_at=datetime.now(UTC),
        content_hash="a" * 64,
        title="Home",
        text="Jane Smith, Head of Operations is amazing.",
        metadata_json={},
    )
    team = SourceSnapshot(
        company_id=company.id,
        url="https://acme-buyers.example/about/team",
        source_type=SourceType.COMPANY_PAGE.value,
        fetched_at=datetime.now(UTC),
        content_hash="b" * 64,
        title="Team",
        text="Jane Smith, Head of Operations leads depot ops.",
        metadata_json={},
    )
    session.add_all([home, team])
    session.flush()
    created = capture_people_from_snapshots(session, company)
    assert len(created) == 1
    assert created[0].source == PersonSource.COMPANY_PAGE.value
    assert created[0].name == "Jane Smith"


def test_research_task_opened_without_person_and_closed_when_added(
    session: Session,
) -> None:
    company = _company()
    session.add(company)
    session.flush()
    opp = _opportunity(company)
    session.add(opp)
    session.flush()

    apply_buyer_role(
        opp,
        recommend_buyer_role_deterministic(opp, company),
    )
    task, created = ensure_research_task(session, company, opp, people=[])
    assert created
    assert task is not None
    assert task.title == research_task_title(opp.buyer_role)
    assert task.status == ResearchTaskStatus.OPEN.value

    person = add_manual_person(
        session, company, name="Pat Lee", role=opp.buyer_role
    )
    task2, created2 = ensure_research_task(
        session, company, opp, people=[person]
    )
    assert not created2
    assert task2 is None
    session.refresh(task)
    assert task.status == ResearchTaskStatus.DONE.value


def test_process_buyers_end_to_end(session: Session) -> None:
    company = _company(size_hint="medium")
    session.add(company)
    session.flush()
    snap = SourceSnapshot(
        company_id=company.id,
        url="https://acme-buyers.example/team",
        source_type=SourceType.COMPANY_PAGE.value,
        fetched_at=datetime.now(UTC),
        content_hash="c" * 64,
        title="Team",
        text="Sam Rivers, COO oversees all depots.",
        metadata_json={},
    )
    opp = _opportunity(company, buyer_role="ops director")
    session.add_all([snap, opp])
    session.flush()

    stats = process_buyers_for_company(session, company, gateway=None)
    assert stats["people_captured"] == 1
    assert stats["roles_recommended"] == 1
    session.refresh(opp)
    assert opp.buyer_role in roles_for_family(opp.solution_family)
    assert opp.buyer_role_rationale

    people = session.scalars(select(Person).where(Person.company_id == company.id)).all()
    assert len(people) == 1
    # COO matches agentic vocabulary → research task should not stay open for COO role
    # if person role matches recommended role.
    open_tasks = session.scalars(
        select(ResearchTask).where(
            ResearchTask.company_id == company.id,
            ResearchTask.status == ResearchTaskStatus.OPEN.value,
        )
    ).all()
    if opp.buyer_role == "COO":
        assert open_tasks == []
    else:
        assert open_tasks  # recommended role differs from captured COO
