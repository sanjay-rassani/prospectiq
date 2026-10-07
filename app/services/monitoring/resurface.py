"""Resurface dormant companies after meaningful change (P8-7 / Q6).

Meaningful change = a new snapshot that produced at least one persisted signal.
Trivial page edits that change hash but yield no signals do not resurface.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Company, CompanyStatus, Signal, SourceSnapshot
from app.services.monitoring.cadence import apply_next_refresh
from app.services.outreach.lifecycle import LifecycleError, transition_company


def maybe_resurface(
    company: Company,
    snapshot: SourceSnapshot,
    new_signals: list[Signal],
    *,
    now: datetime | None = None,
) -> bool:
    """Raise a watch/nurture company back into active research when signals appear."""
    if not new_signals:
        return False
    if snapshot.previous_hash is None:
        # First snapshot is discovery, not resurfacing.
        return False
    if company.status not in {
        CompanyStatus.WATCH.value,
        CompanyStatus.NURTURE.value,
    }:
        return False

    now = now or datetime.now(UTC)
    try:
        transition_company(company, CompanyStatus.RESEARCHED.value)
    except LifecycleError:
        return False
    company.resurfaced_at = now
    # Nudge priority up so Today surfaces it; scoring may refine later.
    if company.priority in {None, "watch", "reject", "nurture"}:
        company.priority = "medium"
    apply_next_refresh(company, now=now)
    return True
