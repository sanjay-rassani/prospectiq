"""Opportunity Score — opportunity-level, may use signals for timing (spec §8.2)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Opportunity, Signal, SignalStrength, SignalType
from app.services.scoring.profile import OperatorProfile, get_operator_profile
from app.services.scoring.types import (
    DimensionScore,
    PriorityBand,
    ScoreResult,
    clamp,
    weighted_total,
)

_STRENGTH = {
    SignalStrength.STRONG.value: 100.0,
    SignalStrength.MODERATE.value: 66.0,
    SignalStrength.WEAK.value: 33.0,
}

_CONFIDENCE = {"high": 85.0, "medium": 60.0, "low": 35.0}

_TIMING_BOOST_TYPES = {
    SignalType.GROWTH_EXPANSION.value,
    SignalType.PRODUCT.value,
    SignalType.AI.value,
    SignalType.LEADERSHIP_STRATEGY.value,
}

_BUYER_KEYWORDS = (
    "ceo",
    "founder",
    "coo",
    "cto",
    "cpo",
    "vp",
    "head",
    "director",
    "owner",
    "chief",
)


def band_for_score(score: float, profile: OperatorProfile) -> PriorityBand:
    t = profile.thresholds
    if score >= t.band_high:
        return PriorityBand.HIGH
    if score >= t.band_medium:
        return PriorityBand.MEDIUM
    if score >= t.band_watch:
        return PriorityBand.WATCH
    return PriorityBand.REJECT


def _linked_signals(opportunity: Opportunity) -> list[Signal]:
    signals: list[Signal] = []
    for link in opportunity.evidence_links or []:
        if link.signal is not None:
            signals.append(link.signal)
    return signals


def _timing_score(signals: list[Signal], now: datetime | None = None) -> tuple[float, str]:
    now = now or datetime.now(UTC)
    if not signals:
        return 20.0, "no linked signals"
    newest: datetime | None = None
    for signal in signals:
        candidate = signal.observed_at
        snap = getattr(signal, "source_snapshot", None)
        if snap is not None and snap.fetched_at is not None:
            candidate = snap.fetched_at if candidate is None else max(candidate, snap.fetched_at)
        if candidate is None:
            candidate = signal.created_at
        if candidate.tzinfo is None:
            candidate = candidate.replace(tzinfo=UTC)
        if newest is None or candidate > newest:
            newest = candidate
    assert newest is not None
    age_days = max(0.0, (now - newest).total_seconds() / 86400.0)
    if age_days <= 3:
        base, label = 100.0, f"signal age {age_days:.1f}d (≤3d)"
    elif age_days <= 7:
        base, label = 80.0, f"signal age {age_days:.1f}d (≤7d)"
    elif age_days <= 14:
        base, label = 60.0, f"signal age {age_days:.1f}d (≤14d)"
    elif age_days <= 30:
        base, label = 40.0, f"signal age {age_days:.1f}d (≤30d)"
    else:
        base, label = 20.0, f"signal age {age_days:.1f}d (>30d)"

    boost_types = [s.type for s in signals if s.type in _TIMING_BOOST_TYPES]
    if boost_types:
        base = clamp(base + 10)
        label += f"; timing boost from {', '.join(sorted(set(boost_types)))}"
    return base, label


def score_opportunity(
    opportunity: Opportunity,
    profile: OperatorProfile | None = None,
    *,
    now: datetime | None = None,
) -> ScoreResult:
    profile = profile or get_operator_profile()
    signals = _linked_signals(opportunity)

    # Evidence strength 25%
    if signals:
        strengths = [_STRENGTH.get(s.strength, 33.0) for s in signals]
        ev_score = sum(strengths) / len(strengths)
        ev_reason = f"{len(signals)} linked signals; mean strength {ev_score:.0f}"
    else:
        ev_score, ev_reason = 10.0, "no linked evidence"

    # Timing 20%
    time_score, time_reason = _timing_score(signals, now=now)

    # Solution fit 20%
    family = opportunity.solution_family
    if family in profile.preferred_solution_families:
        sol_score, sol_reason = 100.0, f"{family} is a preferred family"
    elif profile.preferred_solution_families:
        sol_score, sol_reason = 40.0, f"{family} not in preferred families"
    else:
        sol_score, sol_reason = 60.0, "no preferred families configured; neutral"

    # Potential value 15%
    conf = _CONFIDENCE.get(opportunity.confidence, 35.0)
    unknowns = list(opportunity.unknowns or [])
    value_score = clamp(conf - 5.0 * len(unknowns), low=10.0)
    value_reason = f"confidence={opportunity.confidence}; {len(unknowns)} unknowns"

    # Buyer relevance 10%
    role = (opportunity.buyer_role or "").casefold()
    if not role.strip():
        buyer_score, buyer_reason = 20.0, "no buyer role"
    elif any(k in role for k in _BUYER_KEYWORDS):
        buyer_score, buyer_reason = (
            100.0,
            f"recognised role vocabulary in '{opportunity.buyer_role}'",
        )
    else:
        buyer_score, buyer_reason = 60.0, f"role present but generic: '{opportunity.buyer_role}'"

    # Confidence / unknowns 10%
    cu_score = clamp(conf - 8.0 * len(unknowns))
    cu_reason = f"confidence={opportunity.confidence}; unknowns penalty {8 * len(unknowns)}"

    dimensions = [
        DimensionScore("evidence_strength", 0.25, ev_score, ev_reason),
        DimensionScore("timing", 0.20, time_score, time_reason),
        DimensionScore("solution_fit", 0.20, sol_score, sol_reason),
        DimensionScore("potential_value", 0.15, value_score, value_reason),
        DimensionScore("buyer_relevance", 0.10, buyer_score, buyer_reason),
        DimensionScore("confidence_unknowns", 0.10, cu_score, cu_reason),
    ]
    total = weighted_total(dimensions)
    return ScoreResult(
        total=total,
        dimensions=dimensions,
        band=band_for_score(total, profile),
    )
