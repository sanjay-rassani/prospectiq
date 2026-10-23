"""ORM model registry. Import every model here so Alembic sees them."""

from app.db.base import Base, TimestampMixin
from app.models.company import Company, CompanyStatus, SourceSnapshot, SourceType
from app.models.feeds import (
    AdapterKind,
    DomainFetchPolicy,
    FeedEntry,
    OperatorFeedback,
    SourceFeed,
)
from app.models.job import Job, JobStatus, JobType
from app.models.llm_call import LlmCall
from app.models.outreach import (
    Interaction,
    InteractionDirection,
    InteractionOutcome,
    OutreachChannel,
    OutreachTask,
    OutreachTaskStatus,
)
from app.models.person import (
    CompanyContactChannel,
    FieldEvidenceStatus,
    Person,
    PersonDiscoveryStatus,
    PersonSource,
    ResearchTask,
    ResearchTaskStatus,
)
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
    "AdapterKind",
    "Base",
    "Company",
    "CompanyContactChannel",
    "CompanyStatus",
    "DomainFetchPolicy",
    "FeedEntry",
    "FieldEvidenceStatus",
    "Interaction",
    "InteractionDirection",
    "InteractionOutcome",
    "Job",
    "JobStatus",
    "JobType",
    "LlmCall",
    "OperatorFeedback",
    "Opportunity",
    "OpportunityEvidence",
    "OpportunityStatus",
    "OutreachChannel",
    "OutreachTask",
    "OutreachTaskStatus",
    "Person",
    "PersonDiscoveryStatus",
    "PersonSource",
    "ResearchTask",
    "ResearchTaskStatus",
    "Signal",
    "SignalStrength",
    "SignalType",
    "SolutionFamily",
    "SourceFeed",
    "SourceSnapshot",
    "SourceType",
    "TimestampMixin",
]
