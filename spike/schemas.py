"""Output schemas for the Phase 0 spike.

These are the throwaway harness's most durable output: whatever survives the spike
becomes the basis for app/services/llm schemas in Phase 3.

Design rule throughout: every field must have an "I don't know" representation, so
the model is never cornered into inventing a value. Spec section 6.2 forbids asserting
a problem the evidence does not show.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


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
    """Spec section 6.3. NEGATIVE_WEAK covers stale companies, unclear business,
    no reachable buyer, and hiring-only pages, which must count against a prospect
    rather than for it."""

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

    name: str | None = Field(description="Company name as stated on the page, else null.")
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
        description="True if this is a recruiting, staffing, or job-board business. "
        "These are excluded targets."
    )
    is_job_or_careers_page: bool = Field(
        description="True if the page's primary purpose is advertising employment."
    )
    notable_claims: list[str] = Field(
        description="Specific claims worth remembering: customer counts, funding, scale, awards."
    )
    confidence: Confidence = Field(description="Confidence in the extraction as a whole.")


class Signal(BaseModel):
    type: SignalType
    summary: str = Field(description="One sentence describing what was observed.")
    evidence_excerpt: str = Field(
        description="A VERBATIM span copied character-for-character from the source text "
        "that proves this signal. Never paraphrase. Never write text not in the source."
    )
    strength: SignalStrength
    observed_at: str | None = Field(
        description="ISO date if the source states when this happened, else null."
    )


class SignalList(BaseModel):
    signals: list[Signal] = Field(
        description="Evidence-backed observations. Empty list is a valid and often correct answer."
    )
    no_signal_reason: str | None = Field(
        description="If signals is empty, why. Else null."
    )


class Opportunity(BaseModel):
    """Spec section 7.1. A testable hypothesis, not a service pitch."""

    title: str
    problem_or_change: str = Field(description="The observed change or pain point.")
    project_hypothesis: str = Field(description="What could realistically be built.")
    solution_family: SolutionFamily
    business_outcome: str = Field(
        description="Expected value in qualitative terms. Never invent numbers or percentages."
    )
    why_now: str = Field(description="The current trigger that makes this timely.")
    buyer_role: str = Field(description="Role likely to own this problem and its budget.")
    confidence: Confidence
    risks_or_unknowns: list[str] = Field(description="What is still assumed or missing.")
    supporting_signal_indexes: list[int] = Field(
        description="Zero-based indexes of the input signals that support this hypothesis. "
        "At least one is required."
    )


class OpportunityList(BaseModel):
    opportunities: list[Opportunity] = Field(
        description="Empty list if the evidence does not support any credible project."
    )
    no_opportunity_reason: str | None


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic model to a JSON Schema suitable for constrained decoding.

    Ollama's `format` parameter drives grammar-constrained generation, which needs every
    object closed (`additionalProperties: false`) and every property required. Pydantic
    omits both by default, so we tighten the schema recursively. Optional fields stay
    required but nullable, which is what forces an explicit null instead of omission.
    """
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
