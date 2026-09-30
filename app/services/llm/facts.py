"""extract_company_facts: run only against newly stored snapshots (P3-5, P3-6)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Company, CompanyStatus, LlmCall, SourceSnapshot
from app.services.llm.gateway import CallResult, LlmGateway, OllamaGateway
from app.services.llm.schemas import CompanyFacts

logger = logging.getLogger(__name__)


def apply_facts_to_company(company: Company, facts: CompanyFacts, snapshot: SourceSnapshot) -> None:
    if facts.name:
        company.name = facts.name[:255]
    if facts.one_line_description:
        company.description = facts.one_line_description
    if facts.industry:
        company.industry = facts.industry[:255]
    if facts.size_hint:
        company.size_hint = facts.size_hint.value
    if facts.geography:
        company.geography = ", ".join(facts.geography)[:255]

    company.facts_json = facts.model_dump(mode="json")
    company.facts_snapshot_id = snapshot.id
    company.facts_extracted_at = datetime.now(UTC)
    company.last_researched_at = company.facts_extracted_at

    if facts.is_recruiter_or_staffing or facts.is_job_or_careers_page:
        company.status = CompanyStatus.DISQUALIFIED.value
    elif company.status == CompanyStatus.SEEDED.value:
        company.status = CompanyStatus.RESEARCHED.value


def persist_llm_call(
    session: Session,
    result: CallResult,
    *,
    company_id: object,
    snapshot_id: object,
) -> LlmCall:
    record = LlmCall(
        task=result.task,
        model=result.model,
        prompt_version=result.prompt_version,
        company_id=company_id,
        source_snapshot_id=snapshot_id,
        ok=result.ok,
        attempts=result.attempts,
        seconds=result.seconds,
        raw_output=result.raw_output,
        errors_json=result.errors,
        parsed_json=result.parsed.model_dump(mode="json") if result.parsed else None,
    )
    session.add(record)
    session.flush()
    return record


def extract_company_facts(
    session: Session,
    company: Company,
    snapshot: SourceSnapshot,
    gateway: LlmGateway | None = None,
) -> CallResult | None:
    """Extract facts from a *new* snapshot and apply them to the company.

    Returns None when this path was skipped (no gateway needed). Callers must only invoke
    this after a new SourceSnapshot row was created — never on an unchanged re-fetch.
    """
    owns = gateway is None
    gateway = gateway or OllamaGateway()
    try:
        result = gateway.extract_facts(url=snapshot.url, text=snapshot.text)
        persist_llm_call(
            session, result, company_id=company.id, snapshot_id=snapshot.id
        )
        if result.ok and isinstance(result.parsed, CompanyFacts):
            apply_facts_to_company(company, result.parsed, snapshot)
            session.flush()
        elif not result.ok:
            company.last_error = f"fact extraction failed: {'; '.join(result.errors) or 'unknown'}"
            logger.warning(
                "fact extraction failed for company=%s snapshot=%s: %s",
                company.id,
                snapshot.id,
                result.errors,
            )
        return result
    finally:
        if owns and isinstance(gateway, OllamaGateway):
            gateway.close()
