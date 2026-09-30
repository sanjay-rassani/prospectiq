"""Person and manual research-task models (spec sections 9 and 13)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.signal import Opportunity


class PersonSource(enum.StrEnum):
    """How a person record entered the system. Scraping LinkedIn is never a source."""

    COMPANY_PAGE = "company_page"
    MANUAL = "manual"


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
    role: Mapped[str] = mapped_column(String(255), nullable=False)
    public_profile_url: Mapped[str | None] = mapped_column(String(2048))
    # Nullable by design (§13). Never invent or pattern-guess an address.
    public_email: Mapped[str | None] = mapped_column(String(320))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Snapshot that supplied a company-page capture, when applicable.
    source_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshots.id", ondelete="SET NULL"),
        index=True,
    )

    company: Mapped[Company] = relationship(back_populates="people")


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
