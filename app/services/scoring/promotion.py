"""OUTREACH_READY promotion gate (spec §7.2, task P5-9)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Opportunity, OpportunityStatus, SignalStrength
from app.services.scoring.opportunity_score import _linked_signals
from app.services.scoring.profile import OperatorProfile, get_operator_profile


def _has_recent_or_strong_signal(opportunity: Opportunity, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    signals = _linked_signals(opportunity)
    if not signals:
        return False
    for signal in signals:
        if signal.strength == SignalStrength.STRONG.value:
            return True
        stamp = signal.observed_at or signal.created_at
        snap = getattr(signal, "source_snapshot", None)
        if snap is not None and snap.fetched_at is not None:
            stamp = snap.fetched_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        if (now - stamp).total_seconds() <= 14 * 86400:
            return True
    return False


def promotion_blockers(
    opportunity: Opportunity,
    *,
    company_excluded: bool,
    company_exclusion_reason: str | None,
    profile: OperatorProfile | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Return reasons the opportunity is not outreach-ready. Empty list = eligible."""
    profile = profile or get_operator_profile()
    blockers: list[str] = []

    if opportunity.outreach_ready_override:
        return []

    if company_excluded:
        blockers.append(company_exclusion_reason or "company excluded")
    if not opportunity.hypothesis.strip():
        blockers.append("empty hypothesis")
    if not opportunity.buyer_role.strip():
        blockers.append("missing buyer role")
    if not opportunity.evidence_links:
        blockers.append("no traceable evidence links")
    score = opportunity.opportunity_score
    if score is None or score < profile.thresholds.outreach_ready_min:
        blockers.append(
            f"opportunity score {score} below threshold "
            f"{profile.thresholds.outreach_ready_min}"
        )
    if not _has_recent_or_strong_signal(opportunity, now=now):
        blockers.append("no recent (≤14d) or strong linked signal")
    return blockers


def apply_promotion_status(
    opportunity: Opportunity,
    *,
    company_excluded: bool,
    company_exclusion_reason: str | None = None,
    profile: OperatorProfile | None = None,
    now: datetime | None = None,
) -> bool:
    """Set status to outreach_ready when eligible; leave active/rejected otherwise.

    Does not demote an operator override. Returns True when outreach-ready.
    """
    if opportunity.status in {
        OpportunityStatus.SUPERSEDED.value,
        OpportunityStatus.CLOSED.value,
        OpportunityStatus.REJECTED.value,
    }:
        return False

    blockers = promotion_blockers(
        opportunity,
        company_excluded=company_excluded,
        company_exclusion_reason=company_exclusion_reason,
        profile=profile,
        now=now,
    )
    if not blockers:
        opportunity.status = OpportunityStatus.OUTREACH_READY.value
        opportunity.outreach_ready_at = now or datetime.now(UTC)
        opportunity.promotion_blockers = []
        return True

    opportunity.promotion_blockers = blockers
    if opportunity.status == OpportunityStatus.OUTREACH_READY.value and not (
        opportunity.outreach_ready_override
    ):
        opportunity.status = OpportunityStatus.ACTIVE.value
        opportunity.outreach_ready_at = None
    return False


def override_outreach_ready(opportunity: Opportunity, reason: str) -> None:
    reason = reason.strip()
    if not reason:
        raise ValueError("override reason is required")
    opportunity.outreach_ready_override = True
    opportunity.outreach_ready_override_reason = reason
    opportunity.status = OpportunityStatus.OUTREACH_READY.value
    opportunity.outreach_ready_at = datetime.now(UTC)
    opportunity.promotion_blockers = []
