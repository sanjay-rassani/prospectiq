"""OutreachTask and Interaction models (spec sections 10 and 13)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.person import Person
    from app.models.signal import Opportunity


class OutreachChannel(enum.StrEnum):
    LINKEDIN = "linkedin"
    EMAIL = "email"


class OutreachTaskStatus(enum.StrEnum):
    """Draft lifecycle. Sending stays human — `sent` only records that the operator did it."""

    PENDING_DRAFT = "pending_draft"
    DRAFT_READY = "draft_ready"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    CANCELLED = "cancelled"


class InteractionDirection(enum.StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class InteractionOutcome(enum.StrEnum):
    SENT = "sent"
    REPLIED_INTERESTED = "replied_interested"
    REPLIED_NOT_NOW = "replied_not_now"
    DECLINED = "declined"
    IRRELEVANT = "irrelevant"
    NO_RESPONSE = "no_response"
    CONVERSATION = "conversation"
    OTHER = "other"


class OutreachTask(Base, TimestampMixin):
    __tablename__ = "outreach_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="SET NULL"),
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    # Deterministic brief assembly (§10.1) — never model-generated.
    brief_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    draft: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=OutreachTaskStatus.PENDING_DRAFT.value,
        index=True,
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    opportunity: Mapped[Opportunity] = relationship(back_populates="outreach_tasks")
    person: Mapped[Person | None] = relationship()


class Interaction(Base, TimestampMixin):
    __tablename__ = "interactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="SET NULL"),
        index=True,
    )
    outreach_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outreach_tasks.id", ondelete="SET NULL"),
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_text: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    next_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    next_action_note: Mapped[str | None] = mapped_column(Text)

    opportunity: Mapped[Opportunity] = relationship(back_populates="interactions")
    person: Mapped[Person | None] = relationship()
    outreach_task: Mapped[OutreachTask | None] = relationship()
