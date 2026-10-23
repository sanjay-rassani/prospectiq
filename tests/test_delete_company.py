"""Company hard-delete cascades dependents and clears job rows."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    Interaction,
    Job,
    JobStatus,
    Opportunity,
    OpportunityEvidence,
    OutreachTask,
    Signal,
    SourceSnapshot,
)
from app.services.discovery.delete_company import delete_company


def test_delete_company_cascades(session: Session, client: object) -> None:
    company = Company(name="Gone Co", domain="gone.example", status="researched")
    session.add(company)
    session.flush()

    snap = SourceSnapshot(
        company_id=company.id,
        url="https://gone.example/",
        source_type="company_page",
        fetched_at=datetime.now(UTC),
        content_hash="abc",
        text="hello",
        metadata_json={},
    )
    session.add(snap)
    session.flush()
    company.facts_snapshot_id = snap.id

    signal = Signal(
        company_id=company.id,
        source_snapshot_id=snap.id,
        type="product_launch",
        summary="launched",
        evidence_excerpt="hello",
        strength="medium",
    )
    session.add(signal)
    session.flush()

    opp = Opportunity(
        company_id=company.id,
        title="Deal",
        solution_family="integrations_apis",
        problem_or_change="p",
        hypothesis="h",
        business_outcome="b",
        why_now="now",
        buyer_role="CTO",
        confidence="medium",
        status="active",
        unknowns=[],
    )
    session.add(opp)
    session.flush()
    session.add(
        OpportunityEvidence(
            opportunity_id=opp.id,
            signal_id=signal.id,
            source_snapshot_id=snap.id,
            note="hello",
        )
    )
    task = OutreachTask(
        opportunity_id=opp.id,
        channel="email",
        status="draft_ready",
        draft="hi",
        brief_json={},
    )
    session.add(task)
    session.flush()
    session.add(
        Interaction(
            opportunity_id=opp.id,
            outreach_task_id=task.id,
            channel="email",
            direction="outbound",
            occurred_at=datetime.now(UTC),
            summary="sent",
            outcome="sent",
        )
    )
    session.add(
        Job(
            job_type="refresh_company",
            entity_id=company.id,
            due_at=datetime.now(UTC),
            status=JobStatus.PENDING.value,
            payload_json={},
        )
    )
    session.flush()
    company_id = company.id

    message = delete_company(session, company_id)
    session.commit()

    assert "Gone Co" in message
    assert session.get(Company, company_id) is None
    assert session.scalar(select(func.count()).select_from(SourceSnapshot)) == 0
    assert session.scalar(select(func.count()).select_from(Signal)) == 0
    assert session.scalar(select(func.count()).select_from(Opportunity)) == 0
    assert session.scalar(select(func.count()).select_from(OpportunityEvidence)) == 0
    assert session.scalar(select(func.count()).select_from(OutreachTask)) == 0
    assert session.scalar(select(func.count()).select_from(Interaction)) == 0
    assert session.scalar(select(func.count()).select_from(Job)) == 0

    other = Company(name="Keep", domain="keep.example", status="seeded")
    session.add(other)
    session.flush()
    r = client.post(f"/companies/{other.id}/delete", follow_redirects=False)  # type: ignore[attr-defined]
    assert r.status_code == 303
    assert session.get(Company, other.id) is None


def test_delete_missing_company(session: Session) -> None:
    try:
        delete_company(session, uuid4())
        raise AssertionError("expected LookupError")
    except LookupError:
        pass
