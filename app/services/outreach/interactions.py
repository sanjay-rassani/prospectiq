"""Record and summarize interactions (spec §10 / FR-09)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    Company,
    CompanyStatus,
    Interaction,
    InteractionDirection,
    InteractionOutcome,
    Opportunity,
    OpportunityStatus,
)
from app.services.llm.gateway import CallResult, LlmGateway
from app.services.llm.schemas import InteractionSummary
from app.services.outreach.lifecycle import transition_company, transition_opportunity
from app.services.outreach.stop_rules import (
    apply_outcome_stop_rule,
    apply_unresponsive_rule,
)
from app.services.scoring.profile import get_operator_profile

logger = logging.getLogger(__name__)


def record_interaction(
    session: Session,
    company: Company,
    opportunity: Opportunity,
    *,
    channel: str,
    direction: str,
    outcome: str,
    summary: str = "",
    raw_text: str | None = None,
    person_id: object | None = None,
    occurred_at: datetime | None = None,
    next_action_at: datetime | None = None,
    next_action_note: str | None = None,
    gateway: LlmGateway | None = None,
) -> Interaction:
    """Persist an interaction and advance lifecycle / stop rules deterministically."""
    when = occurred_at or datetime.now(UTC)
    profile = get_operator_profile()

    interaction = Interaction(
        opportunity_id=opportunity.id,
        person_id=person_id,
        channel=channel,
        direction=direction,
        occurred_at=when,
        summary=summary or "",
        raw_text=raw_text,
        outcome=outcome,
        next_action_at=next_action_at,
        next_action_note=next_action_note,
    )
    session.add(interaction)
    session.flush()

    # Optional LLM summary for inbound free text.
    if (
        gateway is not None
        and direction == InteractionDirection.INBOUND.value
        and (raw_text or summary)
    ):
        apply_llm_summary(session, interaction, gateway=gateway)

    if interaction.next_action_at is None and direction == InteractionDirection.INBOUND.value:
        interaction.next_action_at = when + timedelta(
            days=profile.outreach.default_follow_up_days
        )
        if not interaction.next_action_note:
            interaction.next_action_note = "Follow up on reply"

    _advance_for_interaction(company, opportunity, direction, interaction.outcome)
    apply_outcome_stop_rule(company, opportunity, interaction.outcome)
    if direction == InteractionDirection.OUTBOUND.value:
        apply_unresponsive_rule(session, company, opportunity, profile=profile)

    session.flush()
    return interaction


def apply_llm_summary(
    session: Session,
    interaction: Interaction,
    *,
    gateway: LlmGateway,
) -> CallResult:
    from app.services.llm.facts import persist_llm_call

    text = interaction.raw_text or interaction.summary
    result = gateway.summarize_interaction(text=text)
    opportunity = session.get(Opportunity, interaction.opportunity_id)
    persist_llm_call(
        session,
        result,
        company_id=opportunity.company_id if opportunity else None,
        snapshot_id=opportunity.triggering_snapshot_id if opportunity else None,
    )
    if result.ok and isinstance(result.parsed, InteractionSummary):
        if not interaction.summary:
            interaction.summary = result.parsed.summary
        # Operator-editable: only fill blanks / suggest outcome when still generic.
        if interaction.outcome in {
            InteractionOutcome.OTHER.value,
            InteractionOutcome.NO_RESPONSE.value,
            "",
        }:
            suggested = result.parsed.outcome.strip().casefold().replace(" ", "_")
            allowed = {o.value for o in InteractionOutcome}
            if suggested in allowed:
                interaction.outcome = suggested
        if not interaction.next_action_note:
            interaction.next_action_note = result.parsed.suggested_next_action
        if interaction.next_action_at is None and result.parsed.suggested_next_action_at:
            try:
                parsed_at = datetime.fromisoformat(
                    result.parsed.suggested_next_action_at.replace("Z", "+00:00")
                )
                interaction.next_action_at = parsed_at
            except ValueError:
                logger.warning(
                    "bad suggested_next_action_at: %s",
                    result.parsed.suggested_next_action_at,
                )
    session.flush()
    return result


def _advance_for_interaction(
    company: Company,
    opportunity: Opportunity,
    direction: str,
    outcome: str,
) -> None:
    if direction == InteractionDirection.INBOUND.value:
        if opportunity.status == OpportunityStatus.CONTACTED.value:
            transition_opportunity(opportunity, OpportunityStatus.REPLIED.value)
        elif opportunity.status == OpportunityStatus.REPLIED.value and outcome in {
            InteractionOutcome.CONVERSATION.value,
            InteractionOutcome.REPLIED_INTERESTED.value,
        }:
            transition_opportunity(opportunity, OpportunityStatus.CONVERSATION.value)

        if company.status == CompanyStatus.CONTACTED.value:
            transition_company(company, CompanyStatus.REPLIED.value)
        elif company.status == CompanyStatus.REPLIED.value and outcome in {
            InteractionOutcome.CONVERSATION.value,
            InteractionOutcome.REPLIED_INTERESTED.value,
        }:
            transition_company(company, CompanyStatus.CONVERSATION.value)

        if outcome == InteractionOutcome.REPLIED_INTERESTED.value:
            if opportunity.status == OpportunityStatus.REPLIED.value:
                transition_opportunity(
                    opportunity, OpportunityStatus.CONVERSATION.value
                )
            if company.status == CompanyStatus.REPLIED.value:
                transition_company(company, CompanyStatus.CONVERSATION.value)
