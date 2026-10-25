"""Person, company contact channels, and research-task models (spec §9 / §13)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.signal import Opportunity


class PersonSource(enum.StrEnum):
    """How a person record entered the system. Scraping LinkedIn is never a source."""

    COMPANY_PAGE = "company_page"
    MANUAL = "manual"
    ANNOUNCEMENT = "announcement"
    GITHUB = "github"
    IMPORTED = "imported"


class PersonDiscoveryStatus(enum.StrEnum):
    DISCOVERED = "discovered"
    ENRICHED = "enriched"
    NEEDS_RESEARCH = "needs_research"
    ARCHIVED = "archived"


class FieldEvidenceStatus(enum.StrEnum):
    """Honest verification labels — never claim deliverability without a provider."""

    DISCOVERED = "discovered"
    FORMAT_VALID = "format_valid"
    SOURCE_CONFIRMED = "source_confirmed"
    MANUALLY_VERIFIED = "manually_verified"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"


class ResearchTaskStatus(enum.StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class Person(Base, TimestampMixin):
    """A named contact for a company, only from permitted public info or manual entry."""

    __tablename__ = "people"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str | None] = mapped_column(String(255))
    seniority: Mapped[str | None] = mapped_column(String(64))
    public_profile_url: Mapped[str | None] = mapped_column(String(2048))
    # Nullable by design (§13). Never invent or pattern-guess an address.
    public_email: Mapped[str | None] = mapped_column(String(320))
    public_phone: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    discovery_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PersonDiscoveryStatus.DISCOVERED.value,
        index=True,
    )
    email_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FieldEvidenceStatus.UNKNOWN.value
    )
    profile_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FieldEvidenceStatus.UNKNOWN.value
    )
    quality_score: Mapped[float | None] = mapped_column(Float)
    # Per-field provenance: {field: {value, status, source_url, snapshot_id, excerpt, at}}
    fields_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshots.id", ondelete="SET NULL"),
        index=True,
    )

    company: Mapped[Company] = relationship(back_populates="people")


class CompanyContactChannel(Base, TimestampMixin):
    """Generic company inboxes (info@, sales@) — not individual people."""

    __tablename__ = "company_contact_channels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False)  # email|phone
    value: Mapped[str] = mapped_column(String(320), nullable=False)
    label: Mapped[str | None] = mapped_column(String(64))  # info, sales, press, …
    source_url: Mapped[str | None] = mapped_column(String(2048))
    source_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshots.id", ondelete="SET NULL"),
        index=True,
    )
    is_generic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ResearchTask(Base, TimestampMixin):
    """Operator to-do when no reliable person exists for a recommended buyer role (§9.2)."""

    __tablename__ = "research_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ResearchTaskStatus.OPEN.value, index=True
    )

    company: Mapped[Company] = relationship(back_populates="research_tasks")
    opportunity: Mapped[Opportunity] = relationship(back_populates="research_tasks")
