"""ORM model registry. Import every model here so Alembic sees them."""

from app.db.base import Base, TimestampMixin
from app.models.company import Company, CompanyStatus, SourceSnapshot, SourceType
from app.models.llm_call import LlmCall
from app.models.signal import (
    Opportunity,
    OpportunityEvidence,
    OpportunityStatus,
    Signal,
    SignalStrength,
    SignalType,
    SolutionFamily,
)

__all__ = [
    "Base",
    "Company",
    "CompanyStatus",
    "LlmCall",
    "Opportunity",
    "OpportunityEvidence",
    "OpportunityStatus",
    "Signal",
    "SignalStrength",
    "SignalType",
    "SolutionFamily",
    "SourceSnapshot",
    "SourceType",
    "TimestampMixin",
]
