"""Operator profile loader (spec §2.1, task P5-1).

YAML is the v1 store — one file, no settings UI yet (Phase 9). Missing file falls back to
safe defaults so the app still boots.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE_PATH = ROOT / "config" / "operator_profile.yaml"


class ScoreThresholds(BaseModel):
    band_high: float = 75
    band_medium: float = 55
    band_watch: float = 35
    outreach_ready_min: float = 65


class OutreachSettings(BaseModel):
    unresponsive_after_touches: int = 3
    evidence_stale_days: int = 45
    default_follow_up_days: int = 7
    default_channel: str = "linkedin"
    refresh_interval_days: dict[str, int] = Field(
        default_factory=lambda: {
            "high": 2,
            "medium": 7,
            "watch": 14,
            "nurture": 30,
            "reject": 30,
        }
    )
    max_job_attempts: int = 5
    job_backoff_base_seconds: int = 60
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 60


class OperatorProfile(BaseModel):
    positioning: str = "Software and AI solutions provider"
    capabilities: list[str] = Field(default_factory=list)
    preferred_solution_families: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    target_regions: list[str] = Field(default_factory=list)
    excluded_industries: list[str] = Field(default_factory=list)
    excluded_geographies: list[str] = Field(default_factory=list)
    do_not_contact_domains: list[str] = Field(default_factory=list)
    allow_agency_white_label: bool = True
    thresholds: ScoreThresholds = Field(default_factory=ScoreThresholds)
    outreach: OutreachSettings = Field(default_factory=OutreachSettings)


def _load_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"operator profile must be a mapping: {path}")
    return data


@lru_cache
def get_operator_profile(path: str | None = None) -> OperatorProfile:
    profile_path = Path(path) if path else DEFAULT_PROFILE_PATH
    return OperatorProfile.model_validate(_load_raw(profile_path))


def reload_operator_profile(path: str | None = None) -> OperatorProfile:
    get_operator_profile.cache_clear()
    return get_operator_profile(path)
