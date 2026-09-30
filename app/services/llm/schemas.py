"""Pydantic output schemas for LLM tasks.

Graduated from the Phase 0 spike. Every field has an explicit "I don't know" form so the
model is never forced to invent a value (spec section 6.2).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SizeHint(StrEnum):
    SOLO = "solo"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    UNCLEAR = "unclear"


class CustomerType(StrEnum):
    B2B = "b2b"
    B2C = "b2c"
    BOTH = "both"
    UNCLEAR = "unclear"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CompanyFacts(BaseModel):
    """Observable facts only. Nothing here may be inferred from industry norms."""

    name: str | None = Field(
        description="Company name as stated on the page, else null.",
        json_schema_extra={"nuextract_type": "verbatim-string"},
    )
    one_line_description: str | None = Field(
        description="What the business does, in one sentence, using only the page's own claims."
    )
    industry: str | None = Field(description="Industry if stated or unambiguous, else null.")
    products_or_services: list[str] = Field(
        description="Named products or services. Empty list if none named."
    )
    customer_type: CustomerType
    size_hint: SizeHint = Field(
        description="Only from explicit evidence such as team size or office count."
    )
    geography: list[str] = Field(description="Locations or markets explicitly mentioned.")
    technologies_mentioned: list[str] = Field(
        description="Technologies named on the page. Do not guess a likely stack."
    )
    is_recruiter_or_staffing: bool = Field(
        description="True if this is a recruiting, staffing, or job-board business."
    )
    is_job_or_careers_page: bool = Field(
        description="True if the page's primary purpose is advertising employment."
    )
    notable_claims: list[str] = Field(
        description="Specific claims worth remembering: customer counts, funding, scale, awards."
    )
    confidence: Confidence = Field(description="Confidence in the extraction as a whole.")

    @field_validator("is_recruiter_or_staffing", "is_job_or_careers_page", mode="before")
    @classmethod
    def coerce_bool(cls, value: Any) -> Any:
        # NuExtract's boolean stand-in is an enum of the strings "true"/"false".
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0", ""}:
                return False
        return value


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema tightened for Ollama grammar-constrained decoding."""
    schema = model.model_json_schema()

    def tighten(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for value in node.values():
                tighten(value)
        elif isinstance(node, list):
            for item in node:
                tighten(item)

    tighten(schema)
    return schema


def nuextract_template(model: type[BaseModel]) -> dict[str, Any]:
    """NuExtract extraction template derived from the same Pydantic model (decision D-10)."""
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})

    def resolve(node: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in node:
            return defs[node["$ref"].rsplit("/", 1)[-1]]
        return node

    def render(node: dict[str, Any]) -> Any:
        node = resolve(node)
        if "nuextract_type" in node:
            return node["nuextract_type"]
        if "anyOf" in node:
            branches = [b for b in node["anyOf"] if resolve(b).get("type") != "null"]
            return render(branches[0]) if branches else "string"
        if "enum" in node:
            return list(node["enum"])
        node_type = node.get("type")
        if node_type == "object":
            return {name: render(sub) for name, sub in node.get("properties", {}).items()}
        if node_type == "array":
            return [render(node.get("items", {"type": "string"}))]
        if node_type in ("integer", "number"):
            return "number"
        if node_type == "boolean":
            return ["true", "false"]
        if node.get("format") == "date-time":
            return "date-time"
        return "string"

    return render(schema)
