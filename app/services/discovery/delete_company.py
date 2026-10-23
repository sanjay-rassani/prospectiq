"""Hard-delete a company and cascade dependents."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Company, Job


def delete_company(session: Session, company_id: UUID) -> str:
    """Remove a company. DB FKs cascade snapshots, signals, opportunities, etc.

    Jobs use a loose ``entity_id`` (no FK), so pending/historical job rows for this
    company are deleted explicitly. ``facts_snapshot_id`` is cleared first to avoid
    circular FK friction with ORM cascades.
    """
    company = session.get(Company, company_id)
    if company is None:
        raise LookupError(f"company {company_id} not found")

    label = f"{company.name} ({company.domain})"
    company.facts_snapshot_id = None
    session.flush()

    session.execute(delete(Job).where(Job.entity_id == company_id))
    session.delete(company)
    session.flush()
    return f"Deleted {label}"
