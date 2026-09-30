"""Manual research tasks when no reliable person exists (spec §9.2)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    Opportunity,
    Person,
    ResearchTask,
    ResearchTaskStatus,
)
from app.services.buyers.role_map import normalize_to_vocabulary


def person_matches_role(person: Person, role: str) -> bool:
    allowed = (role,)
    return normalize_to_vocabulary(person.role, allowed) is not None or _loose_match(
        person.role, role
    )


def _loose_match(candidate: str, target: str) -> bool:
    a = {
        t
        for t in "".join(ch if ch.isalnum() else " " for ch in candidate.casefold()).split()
    }
    b = {
        t for t in "".join(ch if ch.isalnum() else " " for ch in target.casefold()).split()
    }
    return len(a & b) >= 2


def find_person_for_role(people: list[Person], role: str) -> Person | None:
    for person in people:
        if person_matches_role(person, role):
            return person
    return None


def research_task_title(role: str) -> str:
    return f"Find {role} on LinkedIn"


def ensure_research_task(
    session: Session,
    company: Company,
    opportunity: Opportunity,
    *,
    people: list[Person] | None = None,
) -> tuple[ResearchTask | None, bool]:
    """Ensure research-task state for an opportunity.

    Returns `(task, created)`. When a matching person exists, open tasks are marked done
    and `(None, False)` is returned.
    """
    role = (opportunity.buyer_role or "").strip()
    if not role:
        return None, False

    if people is None:
        people = list(
            session.scalars(select(Person).where(Person.company_id == company.id)).all()
        )
    if find_person_for_role(people, role) is not None:
        open_tasks = session.scalars(
            select(ResearchTask).where(
                ResearchTask.opportunity_id == opportunity.id,
                ResearchTask.status == ResearchTaskStatus.OPEN.value,
            )
        ).all()
        for task in open_tasks:
            task.status = ResearchTaskStatus.DONE.value
        session.flush()
        return None, False

    title = research_task_title(role)
    existing = session.scalar(
        select(ResearchTask).where(
            ResearchTask.opportunity_id == opportunity.id,
            ResearchTask.status == ResearchTaskStatus.OPEN.value,
            ResearchTask.title == title,
        )
    )
    if existing is not None:
        return existing, False

    task = ResearchTask(
        company_id=company.id,
        opportunity_id=opportunity.id,
        title=title,
        status=ResearchTaskStatus.OPEN.value,
    )
    session.add(task)
    session.flush()
    return task, True
