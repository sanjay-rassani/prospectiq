"""Operator feedback → deterministic threshold hints only (P9-5 / §2.3)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Company, OperatorFeedback, Opportunity


def record_feedback(
    session: Session,
    company: Company,
    *,
    verdict: str,
    reason: str,
    opportunity: Opportunity | None = None,
) -> OperatorFeedback:
    verdict = verdict.strip().casefold()
    if verdict not in {"good", "bad"}:
        raise ValueError("verdict must be 'good' or 'bad'")
    reason = reason.strip()
    if not reason:
        raise ValueError("reason is required")

    suggestion: str | None = None
    if verdict == "bad":
        suggestion = (
            "Consider raising outreach_ready_min or tightening target_industries / "
            "excluded_industries in config/operator_profile.yaml. Feedback never trains a model."
        )
    else:
        suggestion = (
            "If this pattern repeats, consider lowering band_watch slightly or adding the "
            "industry to target_industries. Feedback never trains a model."
        )

    row = OperatorFeedback(
        company_id=company.id,
        opportunity_id=opportunity.id if opportunity else None,
        verdict=verdict,
        reason=reason,
        suggested_adjustment=suggestion,
    )
    session.add(row)
    session.flush()
    return row
