"""Discovered lead candidates — projects and organizations before they become companies."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.signal import Opportunity


class LeadKind(enum.StrEnum):
    PROJECT = "project"
    COMPANY = "company"
    INSTITUTION = "institution"
    OTHER = "other"


class IntentClass(enum.StrEnum):
    """Separate from ICP Fit — buying-intent classification."""

    HIGH_INTENT = "high_intent"
    POTENTIAL = "potential_company"
    EMERGING = "emerging"
    LOW_RELEVANCE = "low_relevance"


class LeadStatus(enum.StrEnum):
    NEW = "new"
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    SAVED = "saved"


class SourceCategory(enum.StrEnum):
    P1_INTENT = "p1_intent"
    P2_BUSINESS = "p2_business"
    P3_EDUCATION = "p3_education"
    P4_OTHER = "p4_other"


class DiscoveryLead(Base, TimestampMixin):
    """A scored discovery candidate with source evidence. Not automatically a company."""

    __tablename__ = "discovery_leads"
    __table_args__ = (
        UniqueConstraint(
            "source_kind",
            "listing_id",
            name="uq_discovery_leads_source_listing",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    listing_id: Mapped[str] = mapped_column(String(512), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    excerpt: Mapped[str | None] = mapped_column(Text)
    lead_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    intent_class: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    score_reasons_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    matched_filters_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    detected_requirements_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    buying_intent_indicators_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    location_text: Mapped[str | None] = mapped_column(String(255))
    budget_text: Mapped[str | None] = mapped_column(String(128))
    contract_type: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=LeadStatus.NEW.value, index=True
    )
    operator_notes: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        index=True,
    )
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    company: Mapped[Company | None] = relationship()
    opportunity: Mapped[Opportunity | None] = relationship()
