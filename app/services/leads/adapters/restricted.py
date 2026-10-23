"""Declared but non-searchable marketplace sources — honest availability."""

from __future__ import annotations

from app.config import Settings
from app.services.fetcher import Fetcher
from app.services.leads.adapters.base import (
    AdapterCapability,
    ProgressFn,
    RawCandidate,
    emit,
)
from app.services.leads.filters import TargetingFilters


class RestrictedAdapter:
    """Placeholder that never searches. Used so the UI can show restrictions."""

    def __init__(
        self,
        *,
        key: str,
        label: str,
        category: str,
        description: str,
        limitations: str,
        requires_config: str | None = None,
        priority: int = 90,
    ) -> None:
        self.key = key
        self._label = label
        self._category = category
        self._description = description
        self._limitations = limitations
        self._requires = requires_config
        self._priority = priority

    def capability(self, settings: Settings) -> AdapterCapability:
        return AdapterCapability(
            key=self.key,
            label=self._label,
            category=self._category,
            description=self._description,
            availability="restricted",
            limitations=self._limitations,
            requires_config=self._requires,
            priority=self._priority,
            enabled_by_default=False,
        )

    def search(
        self,
        *,
        session: object,
        filters: TargetingFilters,
        fetcher: Fetcher,
        settings: Settings,
        on_progress: ProgressFn | None,
        limit: int,
    ) -> list[RawCandidate]:
        emit(
            on_progress,
            "warn",
            f"{self._label} is not searchable automatically — {self._limitations}",
        )
        return []
