"""Outreach package — briefs, drafts, interactions, lifecycle."""

from app.services.outreach.brief import assemble_brief, brief_as_markdown
from app.services.outreach.tasks import (
    approve_outreach,
    create_outreach_task,
    mark_sent,
    reject_outreach,
    save_draft,
)

__all__ = [
    "approve_outreach",
    "assemble_brief",
    "brief_as_markdown",
    "create_outreach_task",
    "mark_sent",
    "reject_outreach",
    "save_draft",
]
