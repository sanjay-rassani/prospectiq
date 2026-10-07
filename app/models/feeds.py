"""Source adapter registry and feed configuration (spec §5 / Phase 9)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AdapterKind(enum.StrEnum):
    MANUAL_SEED = "manual_seed"
    COMPANY_PAGE = "company_page"
    RSS = "rss"
    GITHUB_RELEASES = "github_releases"
    CHANGELOG = "changelog"


class SourceFeed(Base, TimestampMixin):
    """An enabled discovery source (RSS or technical)."""

    __tablename__ = "source_feeds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rate_limit_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class FeedEntry(Base, TimestampMixin):
    """Deduped RSS/Atom (or technical) entry."""

    __tablename__ = "feed_entries"
    __table_args__ = (
        UniqueConstraint("feed_id", "entry_id", name="uq_feed_entries_feed_entry_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_feeds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    link: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        index=True,
    )
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class OperatorFeedback(Base, TimestampMixin):
    """Good/bad prospect feedback — threshold hints only, no training (§2.3 / P9-5)."""

    __tablename__ = "operator_feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        index=True,
    )
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)  # good | bad
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_adjustment: Mapped[str | None] = mapped_column(Text)


class DomainFetchPolicy(Base, TimestampMixin):
    """Per-domain fetch options, including optional Playwright fallback (P9-7)."""

    __tablename__ = "domain_fetch_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    playwright_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    rate_limit_seconds: Mapped[float | None] = mapped_column(Float)