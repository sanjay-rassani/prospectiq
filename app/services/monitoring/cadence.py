"""Adaptive refresh cadence (spec §11)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Company, CompanyStatus
from app.services.scoring.profile import OperatorProfile, get_operator_profile

# Spec section 11 defaults (days). High uses the midpoint of 1-3.
_DEFAULT_DAYS = {
    "high": 2,
    "medium": 7,
    "watch": 14,
    "nurture": 30,
    "reject": 30,
    "low": 30,
}


def refresh_interval_days(
    company: Company,
    profile: OperatorProfile | None = None,
) -> int:
    profile = profile or get_operator_profile()
    configured = profile.outreach.refresh_interval_days
    priority = (company.priority or "medium").casefold()
    if company.status == CompanyStatus.NURTURE.value:
        priority = "nurture"
    elif company.status == CompanyStatus.WATCH.value:
        priority = "watch"
    elif company.status in {
        CompanyStatus.DISQUALIFIED.value,
        CompanyStatus.CLOSED.value,
    }:
        return configured.get("reject", _DEFAULT_DAYS["reject"])
    return int(configured.get(priority, _DEFAULT_DAYS.get(priority, 7)))


def compute_next_refresh_at(
    company: Company,
    *,
    now: datetime | None = None,
    profile: OperatorProfile | None = None,
) -> datetime | None:
    """Return the next refresh instant, or None when the company should not be polled."""
    if company.status in {
        CompanyStatus.DISQUALIFIED.value,
        CompanyStatus.CLOSED.value,
    }:
        return None
    now = now or datetime.now(UTC)
    days = refresh_interval_days(company, profile)
    base = company.last_researched_at or now
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    # If already overdue relative to last research, schedule soon (now + small grace).
    candidate = base + timedelta(days=days)
    if candidate < now:
        return now + timedelta(minutes=5)
    return candidate


def apply_next_refresh(
    company: Company,
    *,
    now: datetime | None = None,
    profile: OperatorProfile | None = None,
) -> datetime | None:
    company.next_refresh_at = compute_next_refresh_at(company, now=now, profile=profile)
    return company.next_refresh_at
