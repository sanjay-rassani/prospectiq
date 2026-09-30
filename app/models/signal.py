"""Signal and opportunity ORM models (spec sections 6.3 and 7.1)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.company import Company, SourceSnapshot
    from app.models.person import ResearchTask


class SignalType(enum.StrEnum):
    GROWTH_EXPANSION = "growth_expansion"
    PRODUCT = "product"
    OPERATIONS = "operations"
    TECHNOLOGY = "technology"
    AI = "ai"
    LEADERSHIP_STRATEGY = "leadership_strategy"
    NEGATIVE_WEAK = "negative_weak"


class SignalStrength(enum.StrEnum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class OpportunityStatus(enum.StrEnum):
    ACTIVE = "active"
    OUTREACH_READY = "outreach_ready"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    CLOSED = "closed"


class SolutionFamily(enum.StrEnum):
    AGENTIC_AI_AUTOMATION = "agentic_ai_automation"
    CUSTOM_SOFTWARE_SAAS = "custom_software_saas"
    INTEGRATIONS_APIS = "integrations_apis"
    BACKEND_DATA_SEARCH = "backend_data_search"
    MODERNIZATION_SCALE = "modernization_scale"
    FULL_STACK_PRODUCT = "full_stack_product"


class Signal(Base, TimestampMixin):
    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    strength: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company] = relationship(back_populates="signals")
    source_snapshot: Mapped[SourceSnapshot] = relationship()
    evidence_links: Mapped[list[OpportunityEvidence]] = relationship(
        back_populates="signal"
    )


class Opportunity(Base, TimestampMixin):
    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    solution_family: Mapped[str] = mapped_column(String(64), nullable=False)
    problem_or_change: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    business_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    why_now: Mapped[str] = mapped_column(Text, nullable=False)
    buyer_role: Mapped[str] = mapped_column(String(255), nullable=False)
    buyer_role_rationale: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=OpportunityStatus.ACTIVE.value, index=True
    )
    unknowns: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    score_reasons_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    promotion_blockers: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    outreach_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outreach_ready_override: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    outreach_ready_override_reason: Mapped[str | None] = mapped_column(Text)
    # Snapshot that triggered this generation run (P4-9 change-triggered re-eval).
    triggering_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshots.id", ondelete="SET NULL"),
        index=True,
    )

    company: Mapped[Company] = relationship(back_populates="opportunities")
    evidence_links: Mapped[list[OpportunityEvidence]] = relationship(
        back_populates="opportunity",
        cascade="all, delete-orphan",
    )
    research_tasks: Mapped[list[ResearchTask]] = relationship(
        back_populates="opportunity",
        cascade="all, delete-orphan",
    )


class OpportunityEvidence(Base, TimestampMixin):
    __tablename__ = "opportunity_evidence"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_id",
            "signal_id",
            name="uq_opportunity_evidence_opportunity_signal",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("signals.id", ondelete="SET NULL"),
        index=True,
    )
    source_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshots.id", ondelete="SET NULL"),
        index=True,
    )
    note: Mapped[str | None] = mapped_column(Text)

    opportunity: Mapped[Opportunity] = relationship(back_populates="evidence_links")
    signal: Mapped[Signal | None] = relationship(back_populates="evidence_links")
