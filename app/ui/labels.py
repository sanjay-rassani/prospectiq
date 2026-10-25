"""Human-friendly labels and hover help for status codes shown in the UI."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from markupsafe import Markup


@dataclass(frozen=True, slots=True)
class Term:
    label: str
    help: str


# --- Opportunity pipeline -------------------------------------------------
OPPORTUNITY_STATUS: dict[str, Term] = {
    "active": Term(
        "In review",
        "This deal idea is being evaluated. Not ready to message anyone yet.",
    ),
    "outreach_ready": Term(
        "Ready to approach",
        "Scores and evidence look good enough to prepare a message. "
        "The app still does not send anything — you do.",
    ),
    "contacted": Term(
        "Contacted",
        "You have already reached out about this opportunity.",
    ),
    "replied": Term(
        "Got a reply",
        "The contact replied. Check interactions and plan the next step.",
    ),
    "conversation": Term(
        "In conversation",
        "You are actively talking with someone about this idea.",
    ),
    "project_lead": Term(
        "Project lead",
        "This is shaping into a real project / sales lead.",
    ),
    "watch": Term(
        "Watch",
        "Not approaching now — keep an eye on the company for new signals.",
    ),
    "nurture": Term(
        "Nurture",
        "Soft stay-in-touch. Not urgent, but worth keeping warm.",
    ),
    "superseded": Term(
        "Superseded",
        "A newer opportunity replaced this one for the same company/theme.",
    ),
    "rejected": Term(
        "Rejected",
        "Marked as not a fit. Usually skipped for outreach.",
    ),
    "closed": Term(
        "Closed",
        "Finished or abandoned — no further action expected.",
    ),
}

# --- Company lifecycle ----------------------------------------------------
COMPANY_STATUS: dict[str, Term] = {
    "seeded": Term("Seeded", "Added to the system; research may still be running."),
    "researched": Term("Researched", "Pages were fetched and facts/signals extracted."),
    "qualified": Term("Qualified", "Looks like a plausible customer for your ICP."),
    "watch": Term("Watch", "Keep monitoring; not actively pursuing right now."),
    "nurture": Term("Nurture", "Stay loosely in touch; not urgent."),
    "disqualified": Term("Disqualified", "Not a fit — do not pursue."),
    "closed": Term("Closed", "No further work planned for this company."),
    "contacted": Term("Contacted", "Someone at this company was contacted."),
    "replied": Term("Got a reply", "A contact from this company replied."),
    "conversation": Term("In conversation", "Active discussion with this company."),
    "project_lead": Term("Project lead", "Moving toward a real engagement."),
}

# --- Outreach drafts ------------------------------------------------------
OUTREACH_STATUS: dict[str, Term] = {
    "pending_draft": Term(
        "Draft not ready",
        "Brief exists but the message draft still needs work.",
    ),
    "draft_ready": Term(
        "Draft ready for you",
        "A draft is waiting for your edit/approve. Nothing has been sent.",
    ),
    "approved": Term(
        "Approved — you send it",
        "You approved the text. Send it yourself on LinkedIn or email, then mark sent.",
    ),
    "rejected": Term(
        "Draft rejected",
        "You rejected this draft. Fix or discard it.",
    ),
    "sent": Term(
        "Marked sent",
        "You recorded that you sent this message outside the app.",
    ),
    "cancelled": Term(
        "Cancelled",
        "This outreach task was cancelled.",
    ),
}

CHANNEL: dict[str, Term] = {
    "linkedin": Term("LinkedIn", "You will send via LinkedIn yourself."),
    "email": Term("Email", "Requires a public email on the contact. You send it yourself."),
}

# --- Contacts -------------------------------------------------------------
PERSON_DISCOVERY: dict[str, Term] = {
    "discovered": Term("Discovered", "Found from a public page or manual entry."),
    "enriched": Term("Enriched", "Extra public fields were filled in later."),
    "needs_research": Term(
        "Needs research",
        "Incomplete — dig on the company site or LinkedIn yourself.",
    ),
    "archived": Term("Archived", "Hidden from active lists."),
}

FIELD_EVIDENCE: dict[str, Term] = {
    "discovered": Term("Found", "Seen on a source; not proven deliverable."),
    "format_valid": Term(
        "Looks like an email",
        "Format checks out. This is not proof the inbox works.",
    ),
    "source_confirmed": Term(
        "On a public page",
        "Published on a permitted company page we fetched.",
    ),
    "manually_verified": Term(
        "You verified",
        "You confirmed this field yourself.",
    ),
    "unknown": Term("Unknown", "No solid evidence yet."),
    "conflicting": Term("Conflicting", "Sources disagree — check manually."),
}

# --- Leads / discovery ----------------------------------------------------
LEAD_STATUS: dict[str, Term] = {
    "new": Term("New", "Fresh discovery result — not reviewed yet."),
    "qualified": Term("OK / qualified", "You marked this lead as interesting."),
    "rejected": Term("Rejected", "You rejected this lead — hidden from Active by default."),
    "saved": Term("Saved as company", "Linked or seeded into Companies."),
}

INTENT: dict[str, Term] = {
    "high_intent": Term(
        "High intent",
        "Looks like an explicit ask (project, hire, RFP). Separate from company-fit score.",
    ),
    "potential_company": Term(
        "Potential company",
        "Company-like match without a clear buying ask.",
    ),
    "emerging": Term(
        "Emerging",
        "Change/expansion language — earlier stage interest.",
    ),
    "low_relevance": Term(
        "Low relevance",
        "Weak match to your targeting filters.",
    ),
    # Short badges used in discover UI
    "high": Term("High intent", "Explicit buying/project language."),
    "potential": Term("Potential", "Company-like without a clear ask."),
    "low": Term("Low", "Weak relevance."),
}

# --- Priority bands (ICP / opportunity) -----------------------------------
PRIORITY: dict[str, Term] = {
    "high": Term("High", "Prioritise this — strong fit or timing."),
    "medium": Term("Medium", "Worth a look when you have capacity."),
    "watch": Term("Watch", "Borderline — monitor rather than push hard."),
    "reject": Term("Reject", "Below threshold — usually skip."),
}

# --- Jobs / misc ----------------------------------------------------------
JOB_STATUS: dict[str, Term] = {
    "pending": Term("Queued", "Waiting for the background scheduler."),
    "running": Term("Running", "Work in progress right now."),
    "done": Term("Done", "Finished successfully."),
    "failed": Term("Failed", "Errored — see Failed jobs for details."),
    "cancelled": Term("Cancelled", "Stopped before finishing."),
    "idle": Term("Idle", "No active job."),
}

INTERACTION_OUTCOME: dict[str, Term] = {
    "sent": Term("Sent", "You recorded an outbound send."),
    "replied_interested": Term("Interested reply", "Positive reply."),
    "replied_not_now": Term("Not now", "Polite deferral."),
    "declined": Term("Declined", "Clear no."),
    "irrelevant": Term("Irrelevant", "Wrong person or topic."),
    "no_response": Term("No response", "Silence so far."),
    "conversation": Term("Conversation", "Back-and-forth started."),
    "other": Term("Other", "Catch-all outcome."),
}

INTERACTION_DIRECTION: dict[str, Term] = {
    "outbound": Term("Outbound", "You contacted them."),
    "inbound": Term("Inbound", "They contacted you / replied."),
}

_KINDS: dict[str, dict[str, Term]] = {
    "opportunity": OPPORTUNITY_STATUS,
    "company": COMPANY_STATUS,
    "outreach": OUTREACH_STATUS,
    "channel": CHANNEL,
    "person": PERSON_DISCOVERY,
    "evidence": FIELD_EVIDENCE,
    "lead": LEAD_STATUS,
    "intent": INTENT,
    "priority": PRIORITY,
    "job": JOB_STATUS,
    "outcome": INTERACTION_OUTCOME,
    "direction": INTERACTION_DIRECTION,
}


def lookup_term(code: str | None, kind: str) -> Term:
    raw = (code or "").strip()
    table = _KINDS.get(kind, {})
    if raw in table:
        return table[raw]
    # Fallback: prettify snake_case
    pretty = raw.replace("_", " ").strip() or "—"
    label = pretty[:1].upper() + pretty[1:] if pretty != "—" else pretty
    return Term(label, f"Code: {raw}" if raw else "")


def status_label(code: str | None, kind: str = "opportunity") -> str:
    """Plain friendly label (no HTML)."""
    return lookup_term(code, kind).label


def status_badge(
    code: str | None,
    kind: str = "opportunity",
    css_class: str = "",
) -> Markup:
    """Render a label with hover tooltip explaining the code."""
    term = lookup_term(code, kind)
    classes = "term"
    if css_class:
        classes = f"{css_class} term"
    title = term.help or term.label
    return Markup(
        f'<span class="{escape(classes)}" title="{escape(title)}">{escape(term.label)}</span>'
    )


def priority_badge(code: str | None) -> Markup:
    raw = (code or "").strip()
    band_class = f"band band-{escape(raw)}" if raw else "band"
    return status_badge(code, "priority", css_class=band_class)
