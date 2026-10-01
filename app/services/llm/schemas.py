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


class SignalType(StrEnum):
    """Spec section 6.3. NEGATIVE_WEAK counts against a prospect, not for it."""

    GROWTH_EXPANSION = "growth_expansion"
    PRODUCT = "product"
    OPERATIONS = "operations"
    TECHNOLOGY = "technology"
    AI = "ai"
    LEADERSHIP_STRATEGY = "leadership_strategy"
    NEGATIVE_WEAK = "negative_weak"


class SignalStrength(StrEnum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class SolutionFamily(StrEnum):
    """Spec section 3.2. A hypothesis outside these families is out of scope."""

    AGENTIC_AI_AUTOMATION = "agentic_ai_automation"
    CUSTOM_SOFTWARE_SAAS = "custom_software_saas"
    INTEGRATIONS_APIS = "integrations_apis"
    BACKEND_DATA_SEARCH = "backend_data_search"
    MODERNIZATION_SCALE = "modernization_scale"
    FULL_STACK_PRODUCT = "full_stack_product"


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


class ExtractedSignal(BaseModel):
    type: SignalType
    summary: str = Field(description="One sentence describing what was observed.")
    evidence_excerpt: str = Field(
        description="A VERBATIM span copied character-for-character from the source text.",
        json_schema_extra={"nuextract_type": "verbatim-string"},
    )
    strength: SignalStrength
    observed_at: str | None = Field(
        description="ISO date if the source states when this happened, else null.",
        json_schema_extra={"nuextract_type": "date-time"},
    )


class SignalList(BaseModel):
    signals: list[ExtractedSignal] = Field(
        description="Evidence-backed observations. Empty list is often correct."
    )
    no_signal_reason: str | None = Field(
        description="If signals is empty, why. Else null."
    )


class OpportunityHypothesis(BaseModel):
    """Spec section 7.1. A testable hypothesis, not a service pitch."""

    title: str
    problem_or_change: str = Field(description="The observed change or pain point.")
    project_hypothesis: str = Field(description="What could realistically be built.")
    solution_family: SolutionFamily
    business_outcome: str = Field(
        description="Expected value in qualitative terms. Never invent numbers."
    )
    why_now: str = Field(description="The current trigger that makes this timely.")
    buyer_role: str = Field(description="Role likely to own this problem and its budget.")
    confidence: Confidence
    risks_or_unknowns: list[str] = Field(description="What is still assumed or missing.")
    supporting_signal_indexes: list[int] = Field(
        description="Zero-based indexes of input signals that support this hypothesis."
    )


class OpportunityList(BaseModel):
    opportunities: list[OpportunityHypothesis] = Field(
        description="Empty list if the evidence supports no credible project."
    )
    no_opportunity_reason: str | None


class BuyerRoleRecommendation(BaseModel):
    """Spec §15.1 recommend_buyer_role. `role` must be from the caller's allowed list."""

    role: str = Field(description="Exactly one role from the provided allowed_roles list.")
    rationale: str = Field(description="One or two sentences explaining the choice.")


class OutreachDraft(BaseModel):
    """Spec §15.1 draft_outreach. Concise message; never asserts hypotheses as fact."""

    body: str = Field(description="The outreach message body to send.")
    subject: str | None = Field(
        description="Email subject if channel is email, else null.",
        default=None,
    )


class InteractionSummary(BaseModel):
    """Spec §15.1 summarize_interaction. Operator may edit before acting."""

    outcome: str = Field(
        description=(
            "One of: replied_interested, replied_not_now, declined, irrelevant, "
            "no_response, conversation, other"
        )
    )
    summary: str = Field(description="One or two sentences describing what happened.")
    suggested_next_action: str = Field(
        description="Concrete next step for the operator."
    )
    suggested_next_action_at: str | None = Field(
        description="ISO-8601 date/time for the next action, or null.",
        default=None,
    )


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
