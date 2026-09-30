"""Shared scoring types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PriorityBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    WATCH = "watch"
    REJECT = "reject"


@dataclass
class DimensionScore:
    key: str
    weight: float
    score: float  # 0-100
    reason: str

    @property
    def weighted(self) -> float:
        return self.score * self.weight


@dataclass
class ScoreResult:
    total: float
    dimensions: list[DimensionScore] = field(default_factory=list)
    band: PriorityBand | None = None
    excluded: bool = False
    exclusion_reason: str | None = None

    def reasons_dict(self) -> dict[str, object]:
        return {
            "total": round(self.total, 2),
            "band": self.band.value if self.band else None,
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
            "dimensions": [
                {
                    "key": d.key,
                    "weight": d.weight,
                    "score": round(d.score, 2),
                    "reason": d.reason,
                }
                for d in self.dimensions
            ],
        }


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def weighted_total(dimensions: list[DimensionScore]) -> float:
    if not dimensions:
        return 0.0
    return clamp(sum(d.weighted for d in dimensions))
