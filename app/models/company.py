"""Company and source-snapshot ORM models (spec section 13)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.person import Person, ResearchTask
    from app.models.signal import Opportunity, Signal


class CompanyStatus(enum.StrEnum):
    """Company lifecycle (spec §10.3). Transitions are deterministic Python only (§15.2)."""

    SEEDED = "seeded"  # DISCOVERED
    RESEARCHED = "researched"
    QUALIFIED = "qualified"
    WATCH = "watch"
    NURTURE = "nurture"
    DISQUALIFIED = "disqualified"
    CLOSED = "closed"
    CONTACTED = "contacted"
    REPLIED = "replied"
    CONVERSATION = "conversation"
    PROJECT_LEAD = "project_lead"


class SourceType(enum.StrEnum):
    MANUAL_SEED = "manual_seed"
    COMPANY_PAGE = "company_page"
    RSS = "rss"
    DIRECTORY = "directory"
    TECHNICAL = "technical"


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Dedup key (FR-02). Always store the output of normalize_domain().
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(255))
    size_hint: Mapped[str | None] = mapped_column(String(64))
    geography: Mapped[str | None] = mapped_column(String(255))
    icp_score: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CompanyStatus.SEEDED.value
    )
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seed_url: Mapped[str | None] = mapped_column(String(2048))
    last_error: Mapped[str | None] = mapped_column(Text)

    # Phase 3: structured facts from extract_company_facts, always linked to a snapshot.
    facts_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    facts_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "source_snapshots.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_companies_facts_snapshot_id",
        ),
        index=True,
    )
    facts_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    icp_reasons_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    # Set when a dormant company gets meaningful new evidence (P8-7).
    resurfaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    snapshots: Mapped[list[SourceSnapshot]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="desc(SourceSnapshot.fetched_at)",
        foreign_keys="[SourceSnapshot.company_id]",
    )
    facts_snapshot: Mapped[SourceSnapshot | None] = relationship(
        foreign_keys=[facts_snapshot_id],
        post_update=True,
    )
    signals: Mapped[list[Signal]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="desc(Signal.created_at)",
    )
    opportunities: Mapped[list[Opportunity]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="desc(Opportunity.created_at)",
    )
    people: Mapped[list[Person]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="asc(Person.name)",
    )
    research_tasks: Mapped[list[ResearchTask]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="desc(ResearchTask.created_at)",
    )


class SourceSnapshot(Base, TimestampMixin):
    __tablename__ = "source_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(512))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # etag, last_modified, extractor notes, final_url after redirects, etc.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    company: Mapped[Company] = relationship(
        back_populates="snapshots",
        foreign_keys=[company_id],
    )
