"""Adapter protocol and shared candidate type."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.config import Settings
from app.services.fetcher import Fetcher
from app.services.leads.filters import TargetingFilters

ProgressFn = Callable[[str, str], None]


@dataclass
class AdapterCapability:
    key: str
    label: str
    category: str
    description: str
    availability: str  # available | optional_config | restricted
    limitations: str
    requires_config: str | None = None
    priority: int = 50
    enabled_by_default: bool = False


@dataclass
class RawCandidate:
    source_kind: str
    source_name: str
    source_category: str
    listing_id: str
    url: str
    title: str
    description: str = ""
    excerpt: str | None = None
    location: str | None = None
    budget_text: str | None = None
    contract_type: str | None = None
    published_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class LeadAdapter(Protocol):
    key: str

    def capability(self, settings: Settings) -> AdapterCapability: ...

    def search(
        self,
        *,
        session: Session,
        filters: TargetingFilters,
        fetcher: Fetcher,
        settings: Settings,
        on_progress: ProgressFn | None,
        limit: int,
    ) -> list[RawCandidate]: ...


def emit(on_progress: ProgressFn | None, level: str, message: str) -> None:
    if on_progress is not None:
        on_progress(level, message)
