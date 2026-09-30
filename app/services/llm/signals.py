"""extract_signals with deterministic verbatim evidence gate (P4-2)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Company, Signal, SourceSnapshot
from app.services.llm.evidence import evidence_is_verbatim
from app.services.llm.facts import persist_llm_call
from app.services.llm.gateway import CallResult, LlmGateway, OllamaGateway
from app.services.llm.schemas import ExtractedSignal, SignalList

logger = logging.getLogger(__name__)


def _parse_observed_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def persist_validated_signals(
    session: Session,
    company: Company,
    snapshot: SourceSnapshot,
    extracted: list[ExtractedSignal],
) -> tuple[list[Signal], int]:
    """Persist only signals whose evidence_excerpt is literally in the snapshot text.

    Returns (persisted signals, dropped_count).
    """
    persisted: list[Signal] = []
    dropped = 0
    for item in extracted:
        if not evidence_is_verbatim(item.evidence_excerpt, snapshot.text):
            dropped += 1
            logger.warning(
                "dropping fabricated signal type=%s company=%s excerpt=%r",
                item.type.value,
                company.id,
                item.evidence_excerpt[:120],
            )
            continue
        row = Signal(
            company_id=company.id,
            source_snapshot_id=snapshot.id,
            type=item.type.value,
            summary=item.summary,
            evidence_excerpt=item.evidence_excerpt,
            strength=item.strength.value,
            observed_at=_parse_observed_at(item.observed_at),
        )
        session.add(row)
        persisted.append(row)
    session.flush()
    return persisted, dropped


def extract_and_persist_signals(
    session: Session,
    company: Company,
    snapshot: SourceSnapshot,
    gateway: LlmGateway | None = None,
) -> tuple[list[Signal], CallResult | None, int]:
    """Run extract_signals and persist only verbatim-backed rows."""
    owns = gateway is None
    gateway = gateway or OllamaGateway()
    try:
        result = gateway.extract_signals(url=snapshot.url, text=snapshot.text)
        persist_llm_call(session, result, company_id=company.id, snapshot_id=snapshot.id)
        if not result.ok or not isinstance(result.parsed, SignalList):
            if not result.ok:
                logger.warning(
                    "signal extraction failed for company=%s: %s",
                    company.id,
                    result.errors,
                )
            return [], result, 0
        persisted, dropped = persist_validated_signals(
            session, company, snapshot, result.parsed.signals
        )
        return persisted, result, dropped
    finally:
        if owns and isinstance(gateway, OllamaGateway):
            gateway.close()
