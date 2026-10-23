"""Field-level provenance helpers for contact enrichment."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.models import FieldEvidenceStatus


def field_record(
    *,
    value: str | None,
    status: str,
    source_url: str | None = None,
    snapshot_id: UUID | None = None,
    excerpt: str | None = None,
) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    return {
        "value": value,
        "status": status,
        "source_url": source_url,
        "snapshot_id": str(snapshot_id) if snapshot_id else None,
        "excerpt": (excerpt or "")[:400] or None,
        "at": datetime.now(UTC).isoformat(),
    }


_STATUS_RANK = {
    FieldEvidenceStatus.UNKNOWN.value: 0,
    FieldEvidenceStatus.DISCOVERED.value: 1,
    FieldEvidenceStatus.FORMAT_VALID.value: 2,
    FieldEvidenceStatus.SOURCE_CONFIRMED.value: 3,
    FieldEvidenceStatus.MANUALLY_VERIFIED.value: 4,
    FieldEvidenceStatus.CONFLICTING.value: 1,
}


def should_replace(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> bool:
    if not existing:
        return True
    old_rank = _STATUS_RANK.get(str(existing.get("status")), 0)
    new_rank = _STATUS_RANK.get(str(incoming.get("status")), 0)
    if new_rank > old_rank:
        return True
    if new_rank < old_rank:
        return False
    # Same rank: keep existing value unless empty
    return not existing.get("value") and bool(incoming.get("value"))


def merge_field(
    fields: dict[str, Any],
    key: str,
    incoming: dict[str, Any] | None,
) -> dict[str, Any]:
    if not incoming:
        return fields
    current = fields.get(key) if isinstance(fields.get(key), dict) else None
    if current and current.get("value") and current.get("value") != incoming.get("value"):
        if _STATUS_RANK.get(str(incoming.get("status")), 0) >= _STATUS_RANK.get(
            str(current.get("status")), 0
        ):
            # Conflicting evidence at equal/higher strength — prefer incoming but mark.
            if current.get("value") != incoming.get("value") and _STATUS_RANK.get(
                str(incoming.get("status")), 0
            ) == _STATUS_RANK.get(str(current.get("status")), 0):
                incoming = {**incoming, "status": FieldEvidenceStatus.CONFLICTING.value}
            fields[key] = incoming
        return fields
    if should_replace(current, incoming):
        fields[key] = incoming
    return fields
